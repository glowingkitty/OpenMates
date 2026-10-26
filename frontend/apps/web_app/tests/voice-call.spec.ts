/** Real authenticated STT and ordinary encrypted chat transport in isolated CI.
 * Only external providers use deterministic fixtures; browser sockets, routing,
 * encrypted messages, speech assets and source uploads use their normal owners.
 */
import type { Locator, Page, TestInfo } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
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
  streamPhase?: 'start'|'chunk'|'end'|'error'|'alignment';
  turnTrackId?: string;
  attemptId?: string;
  chunkIndex?: number;
  sequence?: number;
  sourceVersion?: number;
  executionVersion?: number;
  generatedAssetPresent?: boolean;
  generatedAssetId?: string;
  tombstone?: boolean;
  voiceCallBootstrap?: boolean;
  snapshotPurpose?: 'prepare'|'send';
  snapshotSuccess?: boolean;
  snapshotHasCode?: boolean;
  recoveryStatus?: 'completed'|'disabled'|'failed';
  recoveryJobCount?: number;
  recoveryPendingCount?: number;
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
  foreground?: { visible: boolean; focused: boolean };
  failure?: {errorClass?:string;errorCode?:string;httpStatus?:number;module?:string;line?:number};
}
interface HeldSpeechEvidence {
  audio:HTMLAudioElement|null; segmentId:string|null; source:string|null; offset:number;
  firstProgressAt:number|null; playCallsAtHold:number; playCalls:number;
  sourceMse:boolean; beforeProviderEnd:boolean; sequence:number|null;
  nativeErrors:Array<{code:number;observedAt:number}>;
  handoffProgress?:{messageId:string;segmentId:string;audioId:number;observedAt:number;currentTime:number};
}
interface CallEvidence {
  turnDelivery?: TurnDeliveryObservation[];
  inspectDraftAtBootstrap?: (chatId: string) => void;
  inspectDraftAfterReady?: () => Promise<{exists:boolean;wrappedKeyPresent:boolean;wrappedKeyUnchanged:boolean;
    encryptedDraftPresent:boolean;messagesVersion:number|null}>;
  draftDeletionEvents?: Array<{type:string;chatId:string;observedAt:number}>;
  draftAtBootstrap?: { chatId: string; requestedAt: number; completedAt?: number; readFailed?: boolean;
    exists?: boolean; personal?: boolean; ownerCompatible?: boolean; wrappedKeyPresent?: boolean;
    encryptedDraftPresent?: boolean; messagesVersion?: unknown };
  sent: SocketObservation[];
  received: SocketObservation[];
  tracks: MediaStreamTrack[];
  decryptChatContent?: (value: string, rawKey: ArrayBuffer) => Promise<string>;
  boundCaptureTracks?:MediaStreamTrack[];
  memoryBatch?: {socketId:number;entryCount:number;observedAt:number};
  replayMemoryBatch?: () => void;
  holdPrivacySnapshot?: boolean;
  privacySnapshotHeld?: {socketId:number;requestId:string;success:boolean;heldAt:number;releasedAt?:number};
  releasePrivacySnapshot?: () => void;
  privacyNoopReplay?: {socketId:number;entryCount:number;replayedAt:number;producerAt?:number;producerUnchanged?:boolean};
  holdSpeechResponse?: {chatId:string;previousMessageId:string};
  heldSpeechAudio?: {count:number;messageId:string;phases:string[];releasedAt?:number};
  releaseSpeechAudio?: () => void;
  readyHeld?: boolean;
  releaseReady?: () => void;
  bootstrapHeld?: boolean;
  releaseBootstrap?: () => void;
  rejectNextBootstrap?: boolean;
  bootstrapRejectionInjected?: boolean;
  mainSocket?: WebSocket;
  mainSocketId?: number;
  voiceSocketCount?: number;
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
      'inference_temporarily_paused','insufficient_credits','unauthorized','forbidden','websocket_receipt_connection_changed',
      'invalid_request','already_used','receipt_capacity','unavailable','rate_limited','voice_call_bootstrap_failed']);
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
      historyDurability:state?.historyDurability,draftAtBootstrap:state?.draftAtBootstrap,
      speechMediaProof:(window as unknown as {__voiceSpeechMediaProof?:Record<string,number>}).__voiceSpeechMediaProof,
      manualSpeechNative:(window as unknown as {__voiceManualSpeechPlayback?:{native:unknown[]}}).__voiceManualSpeechPlayback?.native.slice(-64),
      draftDeletionEvents:state?.draftDeletionEvents,heldSpeechAudio:state?.heldSpeechAudio,
      memoryBatch:state?.memoryBatch,privacySnapshotHeld:state?.privacySnapshotHeld,privacyNoopReplay:state?.privacyNoopReplay,callUIstatus,
      turnDelivery:state?.turnDelivery?.slice(-48)??[],
      finalTranscriptTurns:state?.received.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='transcript'&&frame.role==='user'&&frame.final).slice(-24).map(ids)??[],
      textInputTurns:state?.sent.filter(frame=>frame.type==='text_input').slice(-24).map(ids)??[],
      canonicalTurns:state?.sent.filter(frame=>frame.type==='chat_message_added').slice(-24).map(frame=>({...ids(frame),voiceMode:frame.voiceMode,heardBoundary:!!frame.heardBoundary}))??[],
      interruptionTargets:state?.received.filter(frame=>frame.type==='audio.interrupted').slice(-24).map(ids)??[],
      admissionEvents:[...(state?.sent??[]).map(frame=>({...frame,direction:'sent'})),
        ...(state?.received??[]).map(frame=>({...frame,direction:'received'}))]
        .filter(frame=>['chat_turn_admit','chat_turn_preflight','chat_turn_preflight_ack','chat_turn_context','chat_turn_context_ack',
          'chat_message_confirmed','personal_send_context_snapshot','personal_send_context_snapshot_result','error'].includes(frame.type))
        .sort((a,b)=>(a.observedAt??0)-(b.observedAt??0)).slice(-48).map(frame=>({...ids(frame),direction:frame.direction,
          status:frame.taskStatus,purpose:frame.snapshotPurpose,success:frame.snapshotSuccess,hasCode:frame.snapshotHasCode,
          code:frame.code?(serverCodes.has(frame.code)?frame.code:'other'):undefined})),
      recoveryEvents:[...(state?.sent??[]).map(frame=>({...frame,direction:'sent'})),
        ...(state?.received??[]).map(frame=>({...frame,direction:'received'}))]
        .filter(frame=>['native_client_lifecycle','native_client_lifecycle_ack','recovery_jobs_available','recovery_outputs_discovery_complete'].includes(frame.type))
        .sort((a,b)=>(a.observedAt??0)-(b.observedAt??0)).slice(-24).map(frame=>({...ids(frame),direction:frame.direction,
          status:frame.recoveryStatus,jobCount:frame.recoveryJobCount,pendingCount:frame.recoveryPendingCount})),
      bootstrapEvents:[...(state?.sent??[]).map(frame=>({...frame,direction:'sent'})),
        ...(state?.received??[]).map(frame=>({...frame,direction:'received'}))]
        .filter(frame=>['voice_call_chat_prepare','encrypted_chat_metadata','encrypted_metadata_stored','start','ready'].includes(frame.type))
        .sort((a,b)=>(a.observedAt??0)-(b.observedAt??0)).slice(-24).map(frame=>({...ids(frame),direction:frame.direction,
          path:frame.path,voiceCallBootstrap:frame.voiceCallBootstrap,keyCiphertextPresent:(frame.ciphertextLength??0)>0})),
      taskEvents:[...(state?.sent??[]),...(state?.received??[])].filter(frame=>['cancel_ai_task','ai_task_initiated','ai_task_cancel_requested','ai_task_ended','ai_task_completed','ai_task_failed','ai_message_ready','ai_response_storage_confirmed','ai_response_storage_failed'].includes(frame.type))
        .sort((a,b)=>(a.observedAt??0)-(b.observedAt??0)).slice(-24).map(frame=>({...ids(frame),status:frame.taskStatus})),
      finalAssistantEvents:state?.received.filter(frame=>frame.type==='ai_message_update'&&frame.finalChunk).slice(-24).map(frame=>({...ids(frame),final:frame.final,awaitingContinuation:frame.awaitingContinuation,
        interruptedByRevocation:frame.interruptedByRevocation,interruptedBySoftLimit:frame.interruptedBySoftLimit}))??[],
      captureRequests:native?.captureRequests??0,detectorReady:native?.detectorReady??0,
      bootstrapControl:{held:state?.bootstrapHeld,rejectionInjected:state?.bootstrapRejectionInjected,voiceSockets:state?.voiceSocketCount??0},
      speechPrimes:native?.speechPrimes??[],
      workersCreated:native?.workersCreated??0,workersTerminated:native?.workersTerminated??0};
  }).catch(()=>({captureFailed:true}));
  // Persist independently of the reporter so completed failures retain their
  // sanitized sender evidence even if the full runner later reaches its limit.
  const diagnosticPath=testInfo.outputPath('voice-call-transport-state.json');
  await writeFile(diagnosticPath,JSON.stringify(diagnostic),'utf8');
  await testInfo.attach('voice-call-transport-state',{path:diagnosticPath,contentType:'application/json'});
});

async function observeRealTransport(page: Page, deferReady = false, bootstrapControls = false): Promise<void> {
  await page.addInitScript(({deferReady,bootstrapControls}) => {
    let holdReady=deferReady;
    let holdBootstrap=bootstrapControls;
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
    window.addEventListener('appSettingsMemoriesSyncReady',event=>{
      const replay=evidence.privacyNoopReplay;
      const detail=(event as CustomEvent).detail;
      if(!replay||replay.producerAt!==undefined||replay.socketId!==evidence.mainSocketId||detail?.entry_count!==replay.entryCount)return;
      // This is the production producer's event, never a test-generated flag.
      replay.producerAt=performance.now();replay.producerUnchanged=detail.privacy_snapshot_unchanged===true;
    });
    const phases=new Set(['queued','started','validating','sender_loading','chat_loading','message_saving','chat_refreshing',
      'chat_updating','canonical_sending','receipt_reading','accepted','refused','failed','canonical_prerequisite','canonical_prerequisite_failed']);
    const reasons=new Set(['invalid_turn','scope_changed','disconnected','personal_chat_unavailable','message_row_unavailable',
      'message_failed','message_waiting_for_connection','predecessor_not_saved','message_identity_conflict','turn_already_settled',
      'immutable_chat_key_mismatch','message_identity_mismatch','preflight_mismatch','recovery_key_mismatch','version_conflict',
      'inference_commitment_mismatch','client_update_required','operation_failed']);
    for(const stage of ['sender','predecessor','predecessor_wait','journal_read','reply_discovery','optimistic_timestamp','model_admission','personal_privacy','fast_admission',
      'connected_accounts','embed_preparation','saved_history','metadata_and_keys','private_context','history_projection',
      'embed_storage','preflight_key','preflight_ciphertext','preflight_journal','preflight_serialization','preflight_receipt',
      'preflight_dispatch','preflight_ack','canonical_dispatch'])reasons.add(stage);
    const errorClasses=new Set(['Error','TypeError','RangeError','SyntaxError','ReferenceError','DOMException','AbortError',
      'OperationError','InvalidStateError','InvalidAccessError','DataError','QuotaExceededError','ConstraintError',
      'TransactionInactiveError','NotFoundError','DataCloneError','NetworkError','PreflightRejectionError','PendingAdmissionCompatibilityError']);
    const errorCodes=new Set(['immutable_chat_key_mismatch','message_identity_mismatch','preflight_mismatch','recovery_key_mismatch',
      'version_conflict','inference_commitment_mismatch','client_update_required','durable_preflight_failed','preflight_expired',
      'preflight_required','team_chat_scope_mismatch','existing_chat_metadata_forbidden','websocket_receipt_connection_changed',
      'privacy_snapshot_invalid','privacy_decryption_failed','privacy_entry_invalid','privacy_entry_missing',
      'privacy_snapshot_rejected','privacy_connection_changed','privacy_snapshot_timeout','privacy_snapshot_unsent',
      'privacy_full_owner_changed','privacy_session_expired','privacy_full_unavailable','privacy_full_owner_unavailable',
      'privacy_owner_unavailable','privacy_owner_changed','privacy_receipt_mismatch','privacy_cache_mismatch',
      'privacy_policy_unconfirmed','privacy_freshness_changed','privacy_filter_changed',
      'pending_message_row_unavailable','pending_message_journal_invalid','reply_recovery_foreground_required',
      'reply_recovery_discovery_timeout','reply_recovery_not_completed']);
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
        phase:detail.phase,reason,observedAt:performance.now(),
        foreground:{visible:document.visibilityState==='visible',focused:document.hasFocus()},
        ...(Object.keys(failure).length?{failure}:{})});
      if(events.length>48)events.splice(0,events.length-48);
    });
    const NativeWebSocket=window.WebSocket;
    const snapshotPurposes=new Map<string,'prepare'|'send'>();
    const snapshotCodes=new Set(['invalid_request','already_used','receipt_capacity','unauthorized','unavailable','rate_limited']);
    let nextSocketId=0;
    window.WebSocket=new Proxy(NativeWebSocket,{construct(Target,args){
      const socket:WebSocket=Reflect.construct(Target,args);
      const socketId=++nextSocketId;
      const path=new URL(String(args[0]),location.href).pathname;
      if(path==='/v1/ws') { evidence.mainSocket=socket; evidence.mainSocketId=socketId; }
      if(path==='/v1/voice-call')evidence.voiceSocketCount=(evidence.voiceSocketCount??0)+1;
      let privacyHoldRequestId:string|null=null;
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
          ...(['encrypted_chat_metadata','voice_call_chat_prepare'].includes(event.type)?{ciphertextLength:typeof payload.encrypted_chat_key==='string'?payload.encrypted_chat_key.length:0,
            plaintext:'content' in payload||'text' in payload}:{}),
          ...(['encrypted_metadata_stored','error'].includes(event.type)?{voiceCallBootstrap:payload.voice_call_bootstrap===true}:{}),
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
          ...(event.type==='assistant_speech_status'?{kind:payload.kind,speechStatus:payload.status,language:payload.language,
            segmentId:payload.segment_id,turnTrackId:safeId(payload.turn_track_id),generatedAssetPresent:!!payload.generated_asset_id,
            generatedAssetId:safeId(payload.generated_asset_id)}:{}),
          ...(['native_client_lifecycle_ack','recovery_jobs_available','recovery_outputs_discovery_complete'].includes(event.type)?{
            recoveryStatus:['completed','disabled','failed'].includes(payload.status)?payload.status:undefined,
            recoveryJobCount:Array.isArray(payload.jobs)?Math.min(payload.jobs.length,50_000):undefined,
            recoveryPendingCount:Number.isSafeInteger(payload.pending_count)&&payload.pending_count>=0&&payload.pending_count<=50_000?payload.pending_count:undefined}:{}),
          ...(event.type==='chat_deleted'?{tombstone:payload.tombstone===true}:{}),
          ...(event.type==='assistant_speech_audio'?{kind:payload.kind,segmentId:safeId(payload.segment_id),
            callId:safeId(payload.voice_call_id),attemptId:safeId(payload.attempt_id),
            streamPhase:['start','chunk','end','error','alignment'].includes(payload.phase)?payload.phase:undefined,
            chunkIndex:Number.isSafeInteger(payload.chunk_index)?payload.chunk_index:undefined,
            sequence:Number.isSafeInteger(payload.sequence)?payload.sequence:undefined,
            sourceVersion:Number.isSafeInteger(payload.source_version)?payload.source_version:undefined,
            executionVersion:Number.isSafeInteger(payload.execution_version)?payload.execution_version:undefined}:{}),
        };
        if(['personal_send_context_snapshot','personal_send_context_snapshot_result'].includes(event.type)){
          const purpose=payload.purpose==='prepare'||payload.purpose==='send'?payload.purpose:undefined;
          if(sent&&frame.requestId&&purpose){
            snapshotPurposes.set(frame.requestId,purpose);
            if(purpose==='send'&&evidence.holdPrivacySnapshot&&privacyHoldRequestId===null)privacyHoldRequestId=frame.requestId;
          }
          frame.snapshotPurpose=purpose??(frame.requestId?snapshotPurposes.get(frame.requestId):undefined);
          if(typeof payload.success==='boolean')frame.snapshotSuccess=payload.success;
          frame.snapshotHasCode=typeof payload.error?.code==='string';
          if(frame.snapshotHasCode)frame.code=snapshotCodes.has(payload.error.code)?payload.error.code:'other';
        }
        if(event.type==='assistant_speech_status'&&Array.isArray(payload.segments)){
          for(const segment of payload.segments)(sent?evidence.sent:evidence.received).push({...frame,
            segmentId:safeId(segment.segment_id),speechStatus:frame.speechStatus==='sealed'?'sealed':taskStatuses.has(segment.status)?segment.status:
              ['registered','generating','cancelled','deleted','invalidated'].includes(segment.status)?segment.status:undefined,
            kind:typeof segment.kind==='string'&&/^[a-z_]{1,64}$/.test(segment.kind)?segment.kind:undefined,
            sequence:Number.isSafeInteger(segment.sequence)?segment.sequence:undefined,
            sourceVersion:Number.isSafeInteger(segment.source_version)?segment.source_version:undefined,
            generatedAssetPresent:!!segment.generated_asset_id,generatedAssetId:safeId(segment.generated_asset_id)});
          return;
        }
        if(sent&&path==='/v1/ws'&&event.type==='voice_call_chat_prepare'&&typeof frame.chatId==='string')
          evidence.inspectDraftAtBootstrap?.(frame.chatId);
        (sent?evidence.sent:evidence.received).push(frame);
      };
      const originalSend=socket.send.bind(socket);
      socket.send=data=>{
        let outgoing=data;
        if(bootstrapControls&&path==='/v1/ws'&&evidence.rejectNextBootstrap&&typeof data==='string'){
          let event;try{event=JSON.parse(data);}catch{event=null;}
          if(event?.type==='voice_call_chat_prepare'){
            evidence.rejectNextBootstrap=false;evidence.bootstrapRejectionInjected=true;
            // One malformed real request, rejected by the production schema.
            // The owner/chat/key remain untouched; no server response is faked.
            outgoing=JSON.stringify({...event,payload:{...event.payload,invalid_bootstrap_field:true}});
          }
        }
        observe(outgoing,true);originalSend(outgoing);
      };
      const heldSpeechEvents:MessageEvent[]=[];
      socket.addEventListener('message',event=>{
        if(typeof event.data!=='string')return;
        if(path==='/v1/ws'){
          let frame;try{frame=JSON.parse(event.data);}catch{frame=null;}
          const payload=frame?.payload;
          if(frame?.type==='app_settings_memories_sync_ready'&&Array.isArray(payload?.entries)
            &&Number.isSafeInteger(payload.entry_count)&&payload.entry_count===payload.entries.length){
            // Ciphertext and versions remain only in this actual socket closure.
            // Replaying the exact authenticated batch exercises the real DB apply
            // outcome and producer; no server authority or no-op flag is invented.
            const original=event;
            evidence.memoryBatch={socketId,entryCount:payload.entry_count,observedAt:performance.now()};
            evidence.replayMemoryBatch=()=>{
              if(evidence.mainSocket!==socket)throw new Error('Memory replay connection changed');
              evidence.privacyNoopReplay={socketId,entryCount:payload.entry_count,replayedAt:performance.now()};
              socket.dispatchEvent(new MessageEvent('message',{data:original.data}));
            };
          }
          if(frame?.type==='personal_send_context_snapshot_result'&&evidence.holdPrivacySnapshot
            &&privacyHoldRequestId!==null&&payload?.request_id===privacyHoldRequestId){
            event.stopImmediatePropagation();
            const held={socketId,requestId:privacyHoldRequestId,success:payload.success===true,heldAt:performance.now()};
            evidence.privacySnapshotHeld=held;
            evidence.releasePrivacySnapshot=()=>{
              delete evidence.holdPrivacySnapshot;privacyHoldRequestId=null;
              if(evidence.privacySnapshotHeld?.releasedAt!==undefined)return;
              evidence.privacySnapshotHeld!.releasedAt=performance.now();
              socket.dispatchEvent(new MessageEvent('message',{data:event.data}));
            };
            return;
          }
        }
        if(path==='/v1/ws'&&evidence.holdSpeechResponse){
          let frame;try{frame=JSON.parse(event.data);}catch{frame=null;}
          const payload=frame?.payload;
          const gate=evidence.holdSpeechResponse;
          if(frame?.type==='assistant_speech_audio'&&payload?.chat_id===gate.chatId&&
            typeof payload.message_id==='string'&&payload.message_id!==gate.previousMessageId){
            // Retain only genuine provider frames in this browser closure.
            // Status/canonical frames pass through. Release replays identical
            // native message events FIFO, without exposing bytes to evidence.
            event.stopImmediatePropagation();heldSpeechEvents.push(event);
            const held:NonNullable<CallEvidence['heldSpeechAudio']>=evidence.heldSpeechAudio??{count:0,messageId:payload.message_id,phases:[]};
            held.count++;
            if(['start','chunk','end','error'].includes(payload.phase)&&!held.phases.includes(payload.phase))held.phases.push(payload.phase);
            evidence.heldSpeechAudio=held;
            evidence.releaseSpeechAudio=()=>{
              delete evidence.holdSpeechResponse;
              if(held.releasedAt===undefined)held.releasedAt=performance.now();
              for(const original of heldSpeechEvents.splice(0))socket.dispatchEvent(new MessageEvent('message',{data:original.data}));
            };
            return;
          }
        }
        try{if(path==='/v1/voice-call'&&JSON.parse(event.data).type==='ready'&&holdReady){
          event.stopImmediatePropagation();evidence.readyHeld=true;evidence.releaseReady=()=>{holdReady=false;evidence.readyHeld=false;socket.dispatchEvent(new MessageEvent('message',{data:event.data}));};return;
        }}catch{return;}
        if(holdBootstrap&&path==='/v1/ws'){
          let frame;try{frame=JSON.parse(event.data);}catch{frame=null;}
          if(frame?.type==='encrypted_metadata_stored'&&frame.payload?.voice_call_bootstrap===true){
            // The server has really committed. Delay only its delivery to the
            // app so the rendered pending-start Cancel remains testable.
            observe(event.data,false);event.stopImmediatePropagation();evidence.bootstrapHeld=true;
            evidence.releaseBootstrap=()=>{
              if(!evidence.bootstrapHeld)return;
              holdBootstrap=false;evidence.bootstrapHeld=false;
              socket.dispatchEvent(new MessageEvent('message',{data:event.data}));
            };
            return;
          }
        }
        observe(event.data,false);
      });
      return socket;
    }});
    const capture=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia=async constraints=>{const stream=await capture(constraints);evidence.tracks.push(...stream.getTracks());return stream;};
  },{deferReady,bootstrapControls});
}

async function evidence(page: Page): Promise<Omit<CallEvidence, 'tracks'>> {
  return page.evaluate(() => {
    const state = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence;
    return { sent: state.sent, received: state.received, draftAtBootstrap: state.draftAtBootstrap,
      draftDeletionEvents: state.draftDeletionEvents };
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

interface SpeechPrimeObservation {
  audioId: number;
  observedAt: number;
  userActivationActive: boolean;
  gestureDispatchActive: boolean;
  gesture: 'start'|'consent'|null;
  gestureAt: number|null;
}
interface NativeVoiceInputEvidence {
  speechPrimes: SpeechPrimeObservation[];
  speechAcknowledgementPosts: number[];
  speechAudioId: (audio: HTMLMediaElement) => number;
  nativeTracks: MediaStreamTrack[];
  outputTracks: MediaStreamTrack[];
  contexts: AudioContext[];
  localToneStarts: number;
  samples: number;
  sampleRate: number;
  capturedSpeech: boolean;
  capturedQuietSamples: number;
  captureRequests: number;
  interruptOnPermission: boolean;
  permissionInterruptions: number;
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
      speechPrimes: [], speechAcknowledgementPosts: [], speechAudioId: () => 0,
      nativeTracks: [], outputTracks: [], contexts: [], localToneStarts: 0, samples: 0, sampleRate: 0,
      capturedSpeech: false, capturedQuietSamples: 0,
      captureRequests: 0, interruptOnPermission: false, permissionInterruptions: 0, speechReady: false, playing: false, workersCreated: 0,
      workersTerminated: 0, detectorReady: 0, readyUploadedSamples: 0, error: false, play: () => {},
    };
    Object.assign(window, { __nativeVoiceInput: state });
    // Observe only the queue's exact public silent grant. Native play and its
    // promise remain unchanged; actual response playback is proved separately.
    const silentPrime = 'data:audio/wav;base64,UklGRnQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YVAAAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==';
    const audioIds = new WeakMap<HTMLMediaElement, number>();
    let nextAudioId = 0;
    state.speechAudioId = audio => {
      let id = audioIds.get(audio);
      if (!id) { id = ++nextAudioId; audioIds.set(audio, id); }
      return id;
    };
    let gesture: { kind: 'start'|'consent'; at: number; event: MouseEvent }|null = null;
    document.addEventListener('click', event => {
      if (!event.isTrusted || !(event.target instanceof Element)) return;
      const start = event.target.closest('[data-testid="voice-call-start"]');
      const button = event.target.closest('button');
      const consent = button?.closest('[data-testid="notification"]') && button.textContent?.trim() === 'Continue';
      if (start || consent) gesture = { kind: start ? 'start' : 'consent', at: performance.now(), event };
    }, true);
    const nativePlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function(...args: Parameters<HTMLMediaElement['play']>) {
      if (this instanceof HTMLAudioElement && this.src === silentPrime) {
        state.speechPrimes.push({ audioId: state.speechAudioId(this), observedAt: performance.now(),
          userActivationActive: navigator.userActivation.isActive,
          gestureDispatchActive: gesture !== null && gesture.event.eventPhase !== Event.NONE,
          gesture: gesture?.kind ?? null, gestureAt: gesture?.at ?? null });
      }
      return nativePlay.apply(this, args);
    };
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
      if (state.interruptOnPermission) {
        state.interruptOnPermission = false;
        // Reproduce a permission sheet suspending the real, gesture-created
        // contexts. Native resume/processing remain production-owned.
        const contexts = state.contexts.filter(context => context.state !== 'closed');
        await Promise.all(contexts.map(context => context.suspend()));
        state.permissionInterruptions += contexts.length;
      }
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

/** Bind actual appended audio objects to their received payload, including pre-seal replay. */
async function observeSpeechMediaSources(page: Page) {
  await page.addInitScript(() => {
    type Binding = { key: string; segmentId: string };
    const sources = new Map<string, string>();
    const proof = { starts: 0, taggedChunks: 0, decodedChunks: 0, matchedAppends: 0, invalidAppends: 0 };
    const starts = new Set<string>();
    const owners = new WeakMap<SourceBuffer, MediaSource>();
    const urls = new WeakMap<MediaSource, Set<string>>();
    const mediaBindings = new WeakMap<MediaSource, Binding | null>();
    const bytesBindings = new WeakMap<object, { binding: Binding; fingerprint: Promise<string> }>();
    const parse = JSON.parse;
    const digest = async (bytes: Uint8Array<ArrayBuffer>) => Array.from(
      new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
    const validId = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
    const version = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
    const bindingFor = (payload: Record<string, unknown>, socketId: number): Binding | null => {
      const identity = [payload.chat_id, payload.voice_call_id, payload.message_id, payload.segment_id, payload.attempt_id];
      if (!identity.every(validId) || ![payload.source_version, payload.execution_version, payload.sequence].every(version)
        || !['voice_prose_clause','voice_prose_turn'].includes(String(payload.kind))
        || payload.kind === 'voice_prose_turn' && payload.sequence !== 0) return null;
      return { key: JSON.stringify([socketId, ...identity, payload.source_version, payload.execution_version, payload.sequence, payload.kind]),
        segmentId: payload.segment_id as string };
    };
    // The application retains parsed early payload objects until their owner seal.
    // Tag that exact object's audio_data reads, rather than the latest arrival,
    // so two identical fixture chunks still have distinct segment provenance.
    let dispatch: { data: string; socketId: number } | undefined;
    let read: { encoded: string; binding: Binding } | undefined;
    let decoded: { raw: string; binding: Binding } | undefined;
    JSON.parse = (text, reviver) => {
      const result = parse(text, reviver);
      if (!reviver && dispatch?.data === text && result?.type === 'assistant_speech_audio') {
        const payload = result.payload;
        if (payload && typeof payload === 'object' && payload.phase === 'chunk' && typeof payload.audio_data === 'string') {
          const binding = bindingFor(payload, dispatch.socketId), encoded = payload.audio_data;
          if (binding && starts.has(binding.key)) { proof.taggedChunks++; Object.defineProperty(payload, 'audio_data', {
            enumerable: true, configurable: true,
            get() {
              const candidate = { encoded, binding }; read = candidate;
              queueMicrotask(() => { if (read === candidate) read = undefined; });
              return encoded;
            },
          }); }
        }
      }
      return result;
    };
    const NativeSocket = window.WebSocket;
    let nextSocket = 0;
    window.WebSocket = new Proxy(NativeSocket, { construct(Target, args) {
      const socket: WebSocket = Reflect.construct(Target, args), socketId = ++nextSocket;
      if (new URL(String(args[0]), location.href).pathname === '/v1/ws') socket.addEventListener('message', event => {
        if (typeof event.data !== 'string') return;
        const current = { data: event.data, socketId }; dispatch = current;
        // Native event callbacks can checkpoint microtasks between listeners.
        // Keep this exact wire frame through the whole message dispatch task.
        setTimeout(() => { if (dispatch === current) dispatch = undefined; }, 0);
        try {
          const frame = parse(event.data), payload = frame?.payload;
          if (frame?.type === 'assistant_speech_audio' && payload?.phase === 'start' && payload.chunk_index === 0) {
            const binding = bindingFor(payload, socketId);
            if (binding && starts.size < 2048) { starts.add(binding.key); proof.starts++; }
          }
        } catch { /* Invalid wire input cannot establish a start. */ }
      });
      return socket;
    } });
    const atob = window.atob.bind(window);
    window.atob = encoded => {
      const candidate = read; read = undefined;
      const raw = atob(encoded);
      if (candidate?.encoded === encoded) {
        const current = { raw, binding: candidate.binding }; decoded = current;
        queueMicrotask(() => { if (decoded === current) decoded = undefined; });
      } else decoded = undefined;
      return raw;
    };
    const from = Uint8Array.from;
    Object.defineProperty(Uint8Array, 'from', { configurable: true, writable: true,
      value: function (this: unknown, ...args: unknown[]) {
        const candidate = decoded; decoded = undefined;
        const bytes: Uint8Array<ArrayBuffer> = Reflect.apply(from, this, args);
        if (candidate && args[0] === candidate.raw && bytes.length === candidate.raw.length
          && bytes.every((byte, index) => byte === candidate.raw.charCodeAt(index))) {
          const fingerprint = digest(bytes);
          // Handle failures even when a rejected stream never appends this object.
          void fingerprint.catch(() => {});
          bytesBindings.set(bytes, { binding: candidate.binding, fingerprint }); proof.decodedChunks++;
        }
        return bytes;
      },
    });
    const create = URL.createObjectURL.bind(URL);
    URL.createObjectURL = object => {
      const url = create(object);
      if (object instanceof MediaSource) {
        const owned = urls.get(object) ?? new Set<string>(); owned.add(url); urls.set(object, owned);
      }
      return url;
    };
    const add = MediaSource.prototype.addSourceBuffer;
    MediaSource.prototype.addSourceBuffer = function (...args) {
      const buffer = add.apply(this, args); owners.set(buffer, this); return buffer;
    };
    const append = SourceBuffer.prototype.appendBuffer;
    SourceBuffer.prototype.appendBuffer = function (bytes) {
      const result = append.call(this, bytes), media = owners.get(this);
      if (!media) return result;
      const provenance = bytesBindings.get(bytes);
      const actual = ArrayBuffer.isView(bytes)
        ? new Uint8Array(bytes.buffer as ArrayBuffer, bytes.byteOffset, bytes.byteLength) : new Uint8Array(bytes as ArrayBuffer);
      const invalidate = () => { proof.invalidAppends++; mediaBindings.set(media, null); for (const url of urls.get(media) ?? []) sources.delete(url); };
      if (!provenance) invalidate();
      else void Promise.all([provenance.fingerprint, digest(actual)]).then(([expected, observed]) => {
        const previous = mediaBindings.get(media);
        if (expected !== observed || previous === null || previous && previous.key !== provenance.binding.key) invalidate();
        else {
          mediaBindings.set(media, provenance.binding); proof.matchedAppends++;
          for (const url of urls.get(media) ?? []) sources.set(url, provenance.binding.segmentId);
        }
      }).catch(invalidate);
      return result;
    };
    Object.assign(window, { __voiceSpeechMediaSources: sources, __voiceSpeechMediaProof: proof });
  });
}

async function nativeVoiceInput(page: Page) {
  return page.evaluate(() => {
    const state = (window as unknown as { __nativeVoiceInput: NativeVoiceInputEvidence }).__nativeVoiceInput;
    return { speechPrimes: state.speechPrimes, speechAcknowledgementPosts: state.speechAcknowledgementPosts,
      samples: state.samples, sampleRate: state.sampleRate, captureRequests: state.captureRequests,
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

async function assertSpeechAutoplayPrimed(page: Page, before: number, audioId?: number): Promise<void> {
  const primes = (await nativeVoiceInput(page)).speechPrimes.filter(prime =>
    prime.observedAt < before && (audioId === undefined || prime.audioId === audioId));
  expect(primes.length, 'the shared speech element must play its silent grant before asynchronous call setup').toBeGreaterThan(0);
  expect(primes.some(prime => prime.userActivationActive && prime.gestureDispatchActive && prime.gesture !== null &&
    prime.gestureAt !== null && prime.gestureAt <= prime.observedAt),
  'native speech priming must retain activation from a real Start or consent click').toBe(true);
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

/** Cleanup attempts are independent; an inaccessible button must neither strand
 * a held real ACK nor replace the strict UI assertion that already failed. */
async function cleanupProjectVoiceDraft(page: Page, testInfo: TestInfo, projectId: string|null,
  apiOrigin: string|null, primaryFailed: boolean): Promise<void> {
  const failedStages: string[] = [];
  try {
    const hangup = page.locator('[data-testid="voice-call-hangup"]:visible');
    if (await hangup.count()) await hangup.click({ timeout: 5000 });
  } catch { failedStages.push('hangup'); }
  try {
    await page.evaluate(() => (window as unknown as { __voiceCallEvidence?: CallEvidence })
      .__voiceCallEvidence?.releaseBootstrap?.());
  } catch { failedStages.push('bootstrap_release'); }
  if (projectId && apiOrigin) {
    try {
      const status = await page.evaluate(async ({ apiOrigin, projectId }) => (await fetch(
        `${apiOrigin}/v1/projects/${projectId}?confirmation_project_id=${encodeURIComponent(projectId)}`,
        { method: 'DELETE', credentials: 'include', signal: AbortSignal.timeout(10_000) })).status,
      { apiOrigin, projectId });
      expect(status, 'cleanup retains exact owned Project deletion confirmation').toBeGreaterThanOrEqual(200);
      expect(status).toBeLessThan(300);
    } catch { failedStages.push('project_delete'); }
  }
  if (failedStages.length) {
    await testInfo.attach('voice-project-cleanup', { body: JSON.stringify({ failedStages, primaryFailurePreserved: primaryFailed }),
      contentType: 'application/json' }).catch(() => {});
    if (!primaryFailed) throw new Error(`Voice Project cleanup failed: ${failedStages.join(', ')}`);
  }
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

/** Meaningful drafts and ordinary conversation history must survive call end. */
async function assertCallChatPreserved(page: Page, chatId: string): Promise<void> {
  expect((await evidence(page)).sent.filter(frame=>frame.type==='delete_empty_call_chat'&&frame.chatId===chatId)).toHaveLength(0);
  expect(await page.evaluate(async id=>{
    const db=await new Promise<IDBDatabase>((resolve,reject)=>{
      const request=indexedDB.open('chats_db');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
    });
    try { return await new Promise<boolean>((resolve,reject)=>{
      const request=db.transaction('chats','readonly').objectStore('chats').get(id);
      request.onsuccess=()=>resolve(Boolean(request.result));request.onerror=()=>reject(request.error);
    }); } finally { db.close(); }
  },chatId)).toBe(true);
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
  // contract-test: direct surface=gui.web assertions=video-call.chat.project-context,video-call.audio.single-owner,video-call.audio.complete-turn-admission,projects.lifecycle.encrypted-crud
  test('registers an unsent personal Project chat before opening its voice call',async({page},testInfo)=>{
    test.setTimeout(120_000);
    await installNativeVoiceInput(page);await observeRealTransport(page);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    let projectId:string|null=null;let apiOrigin:string|null=null;let primaryFailed=false;
    try{
      await page.goto('/projects',{waitUntil:'domcontentloaded'});
      await expect(page.getByTestId('projects-page')).toBeVisible({timeout:30_000});
      const created=page.waitForResponse(response=>response.request().method()==='POST'
        &&new URL(response.url()).pathname==='/v1/projects'&&response.ok());
      await page.getByTestId('project-input-textarea').fill(`Voice draft startup ${Date.now()}`);
      await page.getByTestId('project-input-submit').click();
      await page.getByTestId('project-write-policy-always-ask').check();
      await page.getByTestId('project-write-policy-confirm').click();
      const response=await created;
      // This exact authenticated Personal Project is the only cleanup target.
      expect(new URL(response.url()).searchParams.has('team_id')).toBe(false);
      expect(response.request().postDataJSON()).toMatchObject({write_mode:'always_ask'});
      apiOrigin=new URL(response.url()).origin;
      projectId=(await response.json()).project.project_id;
      expect(projectId).toMatch(/^[0-9a-f-]{36}$/i);
      await expect(page.getByTestId('project-workspace-header')).toBeVisible();
      await page.getByTestId('project-tab-folders').click();
      await page.getByTestId('project-folder-create-menu-button').click();
      await page.evaluate(async projectId=>{
        const open=(name:string)=>new Promise<IDBDatabase>((resolve,reject)=>{
          const request=indexedDB.open(name);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
        });
        const [chats,user]=await Promise.all([open('chats_db'),open('user_db')]);
        const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
        let expectedChatId:string|null=null;
        state.draftDeletionEvents=[];
        let focusedBeforeStartPointerDown=false;
        window.addEventListener('pointerdown',event=>{
          if(!(event.target instanceof Element)||!event.target.closest('[data-testid="voice-call-start"]'))return;
          const editable=document.querySelector('[data-testid="message-editor"] [contenteditable="true"]');
          focusedBeforeStartPointerDown=!!editable&&editable===document.activeElement;
        },{capture:true});
        window.addEventListener('click',event=>{
          if(!(event.target instanceof Element)||!event.target.closest('[data-testid="voice-call-start"]'))return;
          const composer=[...document.querySelectorAll('[data-action="message-input"]')].find(node=>node.getClientRects().length);
          expectedChatId=composer?.getAttribute('data-current-chat-id')??null;
          Object.assign(window,{__voiceProjectDraftBeforeStart:{chatId:expectedChatId,
            focused:focusedBeforeStartPointerDown,
            projectMentionMatches:document.querySelector('[data-testid="message-editor"] [data-type="generic-mention"].mention-project')?.getAttribute('data-mention-syntax')===`@project:${projectId}:read`,
            userRows:document.querySelectorAll('[data-testid="message-user"]').length,
            assistantRows:document.querySelectorAll('[data-testid="message-assistant"]').length,
            starts:state.sent.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='start').length,
            canonicalSends:state.sent.filter(frame=>frame.type==='chat_message_added').length}});
        },{capture:true});
        for(const type of ['chatDeleted','localChatListChanged'])window.addEventListener(type,event=>{
          const detail=(event as CustomEvent).detail;
          if(detail?.chat_id!==expectedChatId||(type==='localChatListChanged'&&detail.draftDeleted!==true))return;
          state.draftDeletionEvents!.push({type,chatId:expectedChatId!,observedAt:performance.now()});
          if(state.draftDeletionEvents!.length>16)state.draftDeletionEvents!.shift();
        });
        state.inspectDraftAtBootstrap=chatId=>{
          delete state.inspectDraftAtBootstrap;
          const proof:NonNullable<CallEvidence['draftAtBootstrap']>={chatId,requestedAt:performance.now()};
          state.draftAtBootstrap=proof;
          const read=(db:IDBDatabase,store:string,key:IDBValidKey)=>new Promise<Record<string,unknown>|string|undefined>((resolve,reject)=>{
            const request=db.transaction(store,'readonly').objectStore(store).get(key);
            request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
          });
          // Both readonly requests are submitted synchronously before native
          // WebSocket.send; only their metadata-only result settles later.
          void Promise.all([read(chats,'chats',chatId),read(user,'user_data','id')]).then(([raw,owner])=>{
            const row=raw&&typeof raw==='object'?raw:undefined;
            // Keep the actual wrapped key inside this browser-only closure.
            // The post-ready read exports equality/availability booleans only.
            const bootstrapWrappedKey=row?.encrypted_chat_key;
            state.inspectDraftAfterReady=async()=>{
              const db=await open('chats_db');
              try{
                const raw=await read(db,'chats',chatId);
                const after=raw&&typeof raw==='object'?raw:undefined;
                return {exists:after?.chat_id===chatId,
                  wrappedKeyPresent:typeof after?.encrypted_chat_key==='string'&&!!after.encrypted_chat_key,
                  wrappedKeyUnchanged:typeof bootstrapWrappedKey==='string'&&after?.encrypted_chat_key===bootstrapWrappedKey,
                  encryptedDraftPresent:typeof after?.encrypted_draft_md==='string'&&!!after.encrypted_draft_md&&after.encrypted_draft_md!=='null',
                  messagesVersion:typeof after?.messages_v==='number'&&Number.isSafeInteger(after.messages_v)?after.messages_v:null};
              }finally{db.close();}
            };
            Object.assign(proof,{exists:row?.chat_id===chatId,
              personal:!!row&&!row.team_id&&row.chat_visibility!=='direct'&&!row.is_incognito&&!row.is_anonymous,
              ownerCompatible:typeof owner==='string'&&!!owner&&!!row&&(!row.user_id||row.user_id===owner),
              wrappedKeyPresent:typeof row?.encrypted_chat_key==='string'&&row.encrypted_chat_key.length>0,
              encryptedDraftPresent:typeof row?.encrypted_draft_md==='string'&&!!row.encrypted_draft_md&&row.encrypted_draft_md!=='null',
              messagesVersion:Number.isSafeInteger(row?.messages_v)?row?.messages_v:null});
          },()=>{proof.readFailed=true;}).finally(()=>{
            proof.completedAt=performance.now();chats.close();user.close();
          });
        };
      },projectId);
      await page.getByTestId('project-create-chat').click();
      await expect(page.getByTestId('message-editor')).toBeVisible();
      // Only focus the existing Project draft; do not type or inject a turn.
      await page.getByTestId('message-field').click();
      // Click immediately after actual editor focus, before slow storage reads
      // or readiness polling can conceal the prop-to-draft-store handoff.
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now',{timeout:45_000});
      const before=await page.evaluate(()=>(window as unknown as {__voiceProjectDraftBeforeStart:{chatId:string;focused:boolean;projectMentionMatches:boolean;
        userRows:number;assistantRows:number;starts:number;canonicalSends:number}}).__voiceProjectDraftBeforeStart);
      const chatId=before.chatId;
      expect(chatId).toMatch(/^[0-9a-f-]{36}$/i);
      expect(before).toMatchObject({focused:true,projectMentionMatches:true,userRows:0,assistantRows:0,starts:0,canonicalSends:0});
      await testInfo.attach('voice-project-draft-identity',{body:JSON.stringify({draftChatId:chatId}),contentType:'application/json'});
      // Same-draft startup must retain its real destination instead of clearing
      // it as an outgoing navigation draft. No turn has been submitted yet.
      await expect(page.locator('[data-action="message-input"]:visible')).toHaveAttribute('data-current-chat-id',chatId!);
      await expect(page.getByTestId('message-editor').locator('[data-type="generic-mention"].mention-project'))
        .toHaveAttribute('data-mention-syntax',`@project:${projectId}:read`);
      const retainedDraft=await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence})
        .__voiceCallEvidence.inspectDraftAfterReady?.());
      expect(retainedDraft).toEqual({exists:true,wrappedKeyPresent:true,wrappedKeyUnchanged:true,
        encryptedDraftPresent:true,messagesVersion:0});
      await testInfo.attach('voice-project-draft-retained-after-ready',{body:JSON.stringify({chatId,...retainedDraft}),contentType:'application/json'});
      const protocol=await evidence(page);
      expect([...protocol.sent,...protocol.received].filter(frame=>frame.chatId===chatId&&
        ['delete_chat','chat_deleted','delete_draft','draft_deleted'].includes(frame.type)),
      'starting the call must not clear or delete its exact destination draft').toHaveLength(0);
      expect(protocol.draftDeletionEvents,'no local chat deletion or draft-cleared event for the bound destination').toEqual([]);
      const localDraft=protocol.draftAtBootstrap;
      expect(localDraft).toMatchObject({chatId,exists:true,personal:true,ownerCompatible:true,
        wrappedKeyPresent:true,encryptedDraftPresent:true,messagesVersion:0});
      expect(localDraft?.readFailed).not.toBe(true);
      await testInfo.attach('voice-project-local-draft',{body:JSON.stringify({draftChatId:chatId,...localDraft}),contentType:'application/json'});
      const registration=protocol.sent.find(frame=>frame.path==='/v1/ws'&&frame.type==='voice_call_chat_prepare'&&frame.chatId===chatId);
      const receipt=protocol.received.find(frame=>frame.path==='/v1/ws'&&frame.type==='encrypted_metadata_stored'
        &&frame.chatId===chatId&&frame.voiceCallBootstrap===true);
      const starts=voiceFrames(protocol,'start');
      const ready=protocol.received.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='ready');
      // Preserve exact draft ownership when diagnosing a different header/chat
      // binding or a transport action change. Never record encrypted wrappers.
      const bootstrap=protocol.sent.filter(frame=>['voice_call_chat_prepare','encrypted_chat_metadata'].includes(frame.type));
      const acknowledgements=protocol.received.filter(frame=>frame.type==='encrypted_metadata_stored');
      await testInfo.attach('voice-project-startup-order',{body:JSON.stringify({draftChatId:chatId,localDraft,
        speechPrimes:(await nativeVoiceInput(page)).speechPrimes,
        bootstrap:bootstrap.map(frame=>({type:frame.type,path:frame.path,chatId:frame.chatId,at:frame.observedAt,
          keyCiphertextPresent:(frame.ciphertextLength??0)>0})),
        acknowledgements:acknowledgements.map(frame=>({path:frame.path,chatId:frame.chatId,at:frame.observedAt,voiceCallBootstrap:frame.voiceCallBootstrap})),
        starts:starts.map(frame=>({chatId:frame.chatId,at:frame.observedAt})),
        ready:ready.map(frame=>({callId:frame.callId,at:frame.observedAt}))}),contentType:'application/json'});
      expect(starts).toHaveLength(1);expect(ready).toHaveLength(1);
      expect(starts[0].chatId,'the header must start the exact existing Project draft shown by its composer').toBe(chatId);
      expect(registration).toBeTruthy();expect(receipt).toBeTruthy();
      await assertSpeechAutoplayPrimed(page,registration!.observedAt!);
      expect(registration!.ciphertextLength).toBeGreaterThan(0);expect(registration!.plaintext).toBe(false);
      expect(registration!.messageId).toBeFalsy();
      expect(ready[0].callId).toBeTruthy();
      expect(localDraft!.requestedAt).toBeGreaterThanOrEqual(registration!.observedAt!);
      expect(localDraft!.completedAt).toBeDefined();
      expect(localDraft!.completedAt!).toBeLessThan(starts[0].observedAt!);
      expect(registration!.observedAt!).toBeLessThan(receipt!.observedAt!);
      expect(receipt!.observedAt!).toBeLessThan(starts[0].observedAt!);
      expect(receipt!.observedAt!).toBeLessThan(ready[0].observedAt!);
      expect(protocol.sent.filter(frame=>frame.type==='chat_message_added'||frame.type==='text_input')).toHaveLength(0);
      expect(protocol.received.filter(frame=>frame.type==='transcript'&&frame.role==='user'&&frame.final)).toHaveLength(0);
      expect(protocol.received.filter(frame=>frame.type==='error'&&frame.path==='/v1/voice-call')).toHaveLength(0);
      await page.getByTestId('voice-call-hangup').click();await assertVoiceInputCleanup(page);
      await assertCallHistoryDurable(page,chatId,ready[0].callId!);
      await assertCallChatPreserved(page,chatId);
    }catch(error){
      primaryFailed=true;throw error;
    }finally{
      await cleanupProjectVoiceDraft(page,testInfo,projectId,apiOrigin,primaryFailed);
    }
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.project-context,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing,projects.lifecycle.encrypted-crud
  test('keeps Project draft Cancel available and restores normal chat with a notification after startup failure',async({page},testInfo)=>{
    test.setTimeout(120_000);
    await installNativeVoiceInput(page);await observeRealTransport(page,false,true);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    let projectId:string|null=null;let apiOrigin:string|null=null;let primaryFailed=false;
    try{
      await page.goto('/projects',{waitUntil:'domcontentloaded'});
      await expect(page.getByTestId('projects-page')).toBeVisible({timeout:30_000});
      const created=page.waitForResponse(response=>response.request().method()==='POST'
        &&new URL(response.url()).pathname==='/v1/projects'&&response.ok());
      await page.getByTestId('project-input-textarea').fill(`Voice startup controls ${Date.now()}`);
      await page.getByTestId('project-input-submit').click();
      await page.getByTestId('project-write-policy-always-ask').check();
      await page.getByTestId('project-write-policy-confirm').click();
      const response=await created;
      expect(new URL(response.url()).searchParams.has('team_id')).toBe(false);
      projectId=(await response.json()).project.project_id;apiOrigin=new URL(response.url()).origin;
      expect(projectId).toMatch(/^[0-9a-f-]{36}$/i);
      await expect(page.getByTestId('project-workspace-header')).toBeVisible();
      await page.getByTestId('project-tab-folders').click();
      await page.getByTestId('project-folder-create-menu-button').click();
      await page.getByTestId('project-create-chat').click();
      await page.getByTestId('message-field').click();
      await expect(page.getByTestId('message-editor').locator('[data-type="generic-mention"].mention-project'))
        .toHaveAttribute('data-mention-syntax',`@project:${projectId}:read`);
      const composer=page.locator('[data-action="message-input"]:visible');
      await expect(composer).toHaveAttribute('data-current-chat-id',/^[0-9a-f-]{36}$/i);
      const chatId=await composer.getAttribute('data-current-chat-id');
      // The actual Project draft exists in the welcome composer; no chat has
      // been selected or turn submitted to make controls appear artificially.
      expect(new URL(page.url()).hash).not.toContain('chat-id=');
      // API-shape regression only: Chromium's native MSE still backs playback.
      // Exercise an MMS-only window after the transport observer captured MSE;
      // this proves constructor selection, not real Safari media behavior.
      expect(await page.evaluate(() => {
        const browser = window as unknown as {
          MediaSource?: typeof MediaSource; ManagedMediaSource?: typeof MediaSource;
        };
        const nativeMediaSource = browser.MediaSource;
        if (!nativeMediaSource?.isTypeSupported('audio/mpeg')) return false;
        Object.defineProperty(window, 'ManagedMediaSource', { configurable: true, writable: true, value: nativeMediaSource });
        Object.defineProperty(window, 'MediaSource', { configurable: true, writable: true, value: undefined });
        return !browser.MediaSource && browser.ManagedMediaSource?.isTypeSupported('audio/mpeg') === true;
      })).toBe(true);
      // Start the exact live draft without dismissing/parking its composer.
      await expect(page.getByTestId('voice-call-start')).toBeVisible();
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      await expect.poll(()=>page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence})
        .__voiceCallEvidence.bootstrapHeld===true),{timeout:30_000}).toBe(true);
      await expect.poll(async()=>(await nativeVoiceInput(page)).captureRequests).toBe(1);
      const pending=await evidence(page);
      expect(pending.received.some(frame=>frame.type==='encrypted_metadata_stored'&&frame.chatId===chatId&&frame.voiceCallBootstrap)).toBe(true);
      expect(voiceFrames(pending,'start')).toHaveLength(0);
      const bar=page.getByTestId('voice-call-bar');const cancel=page.getByTestId('voice-call-hangup');
      await expect(bar).toBeVisible();await expect(bar).toHaveAttribute('aria-busy','true');
      await expect(cancel).toBeVisible();await expect(cancel).toBeEnabled();await expect(cancel).toHaveAccessibleName('Hang up');
      await cancel.click();await expect(bar).toHaveCount(0);await assertVoiceInputCleanup(page);
      expect(await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.bootstrapHeld)).toBe(true);
      await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.releaseBootstrap?.());
      await expect(composer).toHaveAttribute('data-current-chat-id',chatId!);
      // Retry only this bootstrap with one forbidden protocol field. The real
      // server must reject it; this test never fabricates an error or success.
      await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.rejectNextBootstrap=true);
      // Start the exact live draft without dismissing/parking its composer.
      await expect(page.getByTestId('voice-call-start')).toBeVisible();
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      await expect.poll(async()=>(await evidence(page)).received.some(frame=>frame.path==='/v1/ws'&&frame.type==='error'
        &&frame.chatId===chatId&&frame.voiceCallBootstrap&&frame.code==='voice_call_bootstrap_failed'),{timeout:30_000}).toBe(true);
      await expect(page.getByTestId('notification').filter({hasText:'Voice calling is unavailable right now.'})).toHaveCount(1);
      await expect(bar).toHaveCount(0);
      await expect(cancel).toHaveCount(0);
      await expect(page.getByTestId('voice-call-start')).toBeVisible();
      await expect(composer).toHaveAttribute('data-current-chat-id',chatId!);
      await expect(page.getByTestId('voice-call-error')).toHaveCount(0);await assertVoiceInputCleanup(page);
      const protocol=await evidence(page);
      expect(protocol.sent.filter(frame=>frame.type==='voice_call_chat_prepare'&&frame.chatId===chatId)).toHaveLength(2);
      expect(protocol.sent.filter(frame=>frame.type==='chat_message_added'||frame.type==='text_input'||frame.type==='chat_turn_admit')).toHaveLength(0);
      expect(voiceFrames(protocol,'start')).toHaveLength(0);
      expect(protocol.received.filter(frame=>frame.path==='/v1/voice-call'&&frame.type==='ready')).toHaveLength(0);
      expect(protocol.received.filter(frame=>frame.type==='ai_task_initiated')).toHaveLength(0);
      expect(await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.voiceSocketCount??0)).toBe(0);
      expect(protocol.received.filter(frame=>frame.type==='transcript'&&frame.role==='user'&&frame.final)).toHaveLength(0);
      expect((await nativeVoiceInput(page)).captureRequests).toBe(2);
      expect(await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.bootstrapRejectionInjected)).toBe(true);
      await expect(page.getByTestId('message-user')).toHaveCount(0);await expect(page.getByTestId('message-assistant')).toHaveCount(0);
      await expect(composer).toHaveAttribute('data-current-chat-id',chatId!);
    }catch(error){
      primaryFailed=true;throw error;
    }finally{
      await cleanupProjectVoiceDraft(page,testInfo,projectId,apiOrigin,primaryFailed);
    }
  });

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
        if(acknowledgement){
          events.push(method==='POST'?'ack_post':'ack_get');
          if(method==='POST')(window as unknown as {__nativeVoiceInput:NativeVoiceInputEvidence})
            .__nativeVoiceInput.speechAcknowledgementPosts.push(performance.now());
        }
        const response=await nativeFetch(input,init);
        if(acknowledgement){
          if(method==='POST'){
            const json=response.json.bind(response);
            response.json=async()=>{
              const payload=await json();
              if(response.ok&&payload.version===3&&payload.acknowledged===true&&Number.isSafeInteger(payload.acknowledged_at)&&payload.acknowledged_at>0)events.push('ack_saved');
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
      return {ok:response.ok,versionValid:profile.version===3,acknowledged:profile.acknowledged===true,
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
    await expect(notice).toContainText('Mistral transcribes your microphone audio; ElevenLabs v4 Turbo generates assistant voice from reply text and voice settings. Your conversation uses normal OpenMates AI routing and skills. Providers may retain request data under their policies.');
    await expect(notice.getByRole('link',{name:'OpenMates privacy policy',exact:true})).toHaveAttribute('href','/legal/privacy');
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
    const privacyPriming=await nativeVoiceInput(page);
    expect(privacyPriming.speechAcknowledgementPosts).toHaveLength(2);
    await assertSpeechAutoplayPrimed(page,privacyPriming.speechAcknowledgementPosts[0]);
    await testInfo.attach('voice-consent-speech-prime',{body:JSON.stringify({primes:privacyPriming.speechPrimes,
      acknowledgementPosts:privacyPriming.speechAcknowledgementPosts}),contentType:'application/json'});
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
    const reloadRegistration=(await evidence(page)).sent.find(frame=>frame.type==='voice_call_chat_prepare');
    expect(reloadRegistration).toBeTruthy();
    await assertSpeechAutoplayPrimed(page,reloadRegistration!.observedAt!);
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
    await page.evaluate(() => { (window as unknown as {__nativeVoiceInput:NativeVoiceInputEvidence}).__nativeVoiceInput.interruptOnPermission = true; });
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence.readyHeld),
      { timeout: 30_000 }).toBe(true);
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Connecting… Wait to speak.');
    await expect(page.getByTestId('assistant-speech-player')).toHaveCount(0);
    await expect(page.getByTestId('assistant-message-speak')).toHaveCount(0);
    const waiting = await evidence(page);
    expect(await page.evaluate(() => (window as unknown as {__nativeVoiceInput:NativeVoiceInputEvidence}).__nativeVoiceInput.permissionInterruptions)).toBeGreaterThan(0);
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
      // Keep the real browser/server call idle beyond the provider's 30-second
      // application-audio timeout. Provider unit/live checks prove the silent
      // transport keepalive; this checks that the client stays idle and resumes
      // the same authenticated call without charging synthetic microphone time.
      const idleStarted=Date.now();
      await expect.poll(()=>Date.now()-idleStarted,{timeout:41_000,intervals:[1_000]}).toBeGreaterThan(35_000);
      const afterLongIdle=await evidence(page);
      expect(voiceFrames(afterLongIdle,'mic_audio')).toHaveLength(idleCount);
      expect(voiceFrames(afterLongIdle,'start')).toHaveLength(1);
      expect(afterLongIdle.received.filter(frame=>frame.type==='ready'&&frame.path==='/v1/voice-call')).toHaveLength(1);
      expect(afterLongIdle.received.filter(frame=>frame.path==='/v1/voice-call'&&(frame.type==='error'||frame.type==='ended'))).toHaveLength(0);
      await expect(page.getByTestId('voice-call-timer')).toHaveText(timer!);
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Speak to resume call.');
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

  // contract-test: direct surface=gui.web assertions=video-call.chat.call-events,video-call.lifecycle.recovery-and-billing
  test('keeps lifecycle-only calls neutral in another tab and removes their empty chat after hangup',async({page},testInfo)=>{
    test.setTimeout(120_000);
    await page.addInitScript(()=>{
      const decisions:Array<Record<string,boolean|number|string>>=[];
      Object.assign(window,{__voiceCallCleanupDecisions:decisions});
      window.addEventListener('voiceCallEmptyChatCleanupDecision',event=>{
        if(decisions.length<16)decisions.push((event as CustomEvent).detail);
      });
    });
    const authority={guardedConnection:false,requested:false,echoed:false,matched:false,startMatched:false};
    const lifecycleVersions:number[]=[];
    let cleanupToken:string|undefined;
    page.on('websocket',socket=>{
      const connection=new URL(socket.url());
      if(connection.pathname==='/v1/ws')authority.guardedConnection=connection.searchParams.get('empty_call_cleanup_guard')==='1';
      socket.on('framesent',frame=>{
        try {
          const event=JSON.parse(String(frame.payload));const payload=event.payload??event;
          if(event.type==='voice_call_chat_prepare'){
            cleanupToken=typeof payload.cleanup_attempt_id==='string'?payload.cleanup_attempt_id:undefined;
            authority.requested=!!cleanupToken;
          }
          if(event.type==='start')authority.startMatched=!!cleanupToken&&payload.cleanup_attempt_id===cleanupToken;
        } catch { /* Only bounded booleans are retained from these frames. */ }
      });
      socket.on('framereceived',frame=>{
        try {
          const event=JSON.parse(String(frame.payload));const payload=event.payload??event;
          if(event.type==='encrypted_metadata_stored'&&payload.voice_call_bootstrap===true){
            authority.echoed=typeof payload.cleanup_attempt_id==='string';
            authority.matched=!!cleanupToken&&payload.cleanup_attempt_id===cleanupToken;
          }
          if(event.type==='system_message_confirmed'&&Number.isSafeInteger(payload.messages_v))lifecycleVersions.push(payload.messages_v);
        } catch { /* No payload text, token or ciphertext is attached. */ }
      });
    });
    const cleanupResults:Array<{chat_id:string;accepted:boolean}>=[];
    const deletedByPage=new Map<Page,string[]>([[page,[]]]);
    const trackDeletion=(target:Page)=>target.on('websocket',socket=>socket.on('framereceived',frame=>{
      try {
        const event=JSON.parse(String(frame.payload));const payload=event.payload??event;
        if(event.type==='empty_call_chat_cleanup_result') cleanupResults.push(payload);
        if(event.type==='chat_deleted') deletedByPage.get(target)!.push(payload.chat_id);
      } catch { /* Other frame kinds do not acknowledge cleanup. */ }
    }));
    trackDeletion(page);
    await installNativeVoiceInput(page);await observeRealTransport(page);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    const other=await page.context().newPage();deletedByPage.set(other,[]);trackDeletion(other);
    const systemEvents:Array<{chat_id:string;data:{message_id:string;status?:string}}>=[];
    other.on('websocket',socket=>socket.on('framereceived',frame=>{
      try {
        const event=JSON.parse(String(frame.payload));
        if(event.type==='new_system_message') systemEvents.push(event.payload??event);
      } catch { /* Non-JSON transport frames do not carry system messages. */ }
    }));
    try {
      await other.goto(page.url());
      await expect(other.locator('[data-testid="voice-call-start"]:visible')).toBeVisible();
      // Opening the observer tab changes the browser's foreground page. Select
      // the caller for its real activation gesture, just as a user would.
      await page.bringToFront();
      await expect.poll(()=>page.evaluate(()=>document.visibilityState==='visible'&&document.hasFocus())).toBe(true);
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
      const ready=(await evidence(page)).received.find(frame=>frame.type==='ready'&&frame.path==='/v1/voice-call')!;
      const startedId=`00000000-voice-call-${ready.callId}-started`;
      await expect.poll(()=>systemEvents.find(event=>event.data?.message_id===startedId)).toBeTruthy();
      const started=systemEvents.find(event=>event.data?.message_id===startedId)!;
      expect(started.data.status).toBe('synced');
      await other.bringToFront();
      await other.goto(`/#chat-id=${started.chat_id}`);
      await expect(other.getByText('Credits needed...', {exact:true})).toHaveCount(0);
      await expect(other.getByText('Not enough credits', {exact:true})).toHaveCount(0);
      await expect.poll(()=>other.evaluate(async messageId=>{
        const db=await new Promise<IDBDatabase>((resolve,reject)=>{
          const request=indexedDB.open('chats_db');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
        });
        try { return await new Promise<string|undefined>((resolve,reject)=>{
          const request=db.transaction('messages','readonly').objectStore('messages').get(messageId);
          request.onsuccess=()=>resolve(request.result?.status);request.onerror=()=>reject(request.error);
        }); } finally { db.close(); }
      },started.data.message_id)).toBe('synced');
      await page.bringToFront();
      await expect.poll(()=>page.evaluate(()=>document.visibilityState==='visible'&&document.hasFocus())).toBe(true);
      await page.getByTestId('voice-call-hangup').click();
      await assertVoiceInputCleanup(page);
      // Empty-call retirement waits for durable lifecycle persistence and final
      // billing settlement. This budget covers completion, not call startup.
      await expect.poll(()=>cleanupResults.some(result=>result.chat_id===started.chat_id&&result.accepted),
        {timeout:30_000}).toBe(true);
      for(const tab of [page,other]) {
        await expect.poll(()=>deletedByPage.get(tab)!.includes(started.chat_id),{timeout:30_000}).toBe(true);
        await expect.poll(()=>tab.evaluate(async chatId=>{
          const db=await new Promise<IDBDatabase>((resolve,reject)=>{
            const request=indexedDB.open('chats_db');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
          });
          try { return await new Promise<boolean>((resolve,reject)=>{
            const request=db.transaction('chats','readonly').objectStore('chats').get(chatId);
            request.onsuccess=()=>resolve(!request.result);request.onerror=()=>reject(request.error);
          }); } finally { db.close(); }
        },started.chat_id),{timeout:30_000}).toBe(true);
      }
    } finally {
      const decisions=await page.evaluate(()=>(window as unknown as {__voiceCallCleanupDecisions?:unknown[]}).__voiceCallCleanupDecisions??[]);
      await testInfo.attach('empty-call-cleanup-decisions',{body:JSON.stringify({authority,lifecycleVersions,decisions}),contentType:'application/json'});
      await other.close();
    }
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
    await assertCallChatPreserved(page,chatId);
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

  // contract-test: direct surface=gui.web assertions=video-call.privacy,video-call.audio.single-owner,video-call.audio.spoken-rich-response,assistant-speech.playback.live-call-streaming,assistant-speech.on-demand.generate-missing-only,assistant-speech.lifecycle.disable-delete-invalidate
  test('keeps call audio ephemeral, caches later manual Speak once, and removes its audio access when the chat is deleted',async({page},testInfo)=>{
    test.setTimeout(240_000);
    // Isolated CI has trusted speech replay but no paid Mistral credentials.
    // Model only that available provider capability, as in the existing speech
    // recording spec; Speak, authorization, storage, replay and deletion stay real.
    let speechCapabilityResponses=0;
    await page.route(/\/v1\/apps\/metadata(?:\?.*)?$/,async route=>{
      const response=await route.fetch();expect(response.ok()).toBe(true);
      const metadata=await response.json();
      metadata.assistant_speech_available=true;
      speechCapabilityResponses++;
      await route.fulfill({response,json:metadata});
    });
    await page.addInitScript(()=>{
      const state={epoch:0,ended:[] as Array<{trackId:string;observedAt:number}>,
        progress:[] as Array<{epoch:number;segmentId:string|null;sourceKind:string;currentTime:number}>,
        native:[] as Array<{event:string;epoch:number;sourceKind:string;mapped:boolean;currentTime:number;paused:boolean;ended:boolean;errorCode:number|null}>};
      const mseUrls=new Set<string>();const create=URL.createObjectURL.bind(URL);
      URL.createObjectURL=object=>{const url=create(object);if(object instanceof MediaSource)mseUrls.add(url);return url;};
      type Generation={source:string;epoch:number;segmentId:string|null;lastTime:number;reported:boolean;sampled:boolean};
      const generations=new WeakMap<HTMLMediaElement,Generation>();
      const storedBindings=new Map<string,string|null>();
      const observed=new WeakSet<HTMLMediaElement>();
      const sourceKind=(source:string)=>mseUrls.has(source)?'mse':source.startsWith('blob:')?'stored_blob':'other';
      const segment=(generation:Generation)=>sourceKind(generation.source)==='mse'
        ?(window as unknown as {__voiceSpeechMediaSources:Map<string,string>}).__voiceSpeechMediaSources.get(generation.source)??null
        :generation.segmentId;
      const record=(audio:HTMLMediaElement,event:string,generation:Generation)=>{
        if(state.native.length<64)state.native.push({event,epoch:generation.epoch,sourceKind:sourceKind(generation.source),mapped:!!segment(generation),
          currentTime:Number.isFinite(audio.currentTime)?audio.currentTime:0,paused:audio.paused,ended:audio.ended,errorCode:audio.error?.code??null});
      };
      const play=HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play=function(...args:Parameters<HTMLMediaElement['play']>){
        if(!(this instanceof HTMLAudioElement))return play.apply(this,args);
        let generation=generations.get(this);
        if(!generation||generation.source!==this.src||generation.epoch!==state.epoch){
          generation={source:this.src,epoch:state.epoch,segmentId:null,lastTime:0,reported:false,sampled:false};generations.set(this,generation);
        }
        if(!observed.has(this)){
          observed.add(this);
          this.addEventListener('ended',()=>{
            const current=generations.get(this);if(!current||current.source!==this.src)return;
            record(this,'ended',current);const segmentId=segment(current);
            if(segmentId)state.ended.push({trackId:segmentId,observedAt:performance.now()});
          },{capture:true});
          this.addEventListener('timeupdate',()=>{
            const current=generations.get(this);if(!current||current.source!==this.src)return;
            if(!current.sampled&&this.currentTime>0){current.sampled=true;record(this,'timeupdate',current);}
            const segmentId=segment(current);
            if(!current.reported&&segmentId&&!this.paused&&!this.ended&&this.currentTime>current.lastTime+0.001){
              state.progress.push({epoch:current.epoch,segmentId,sourceKind:sourceKind(current.source),currentTime:this.currentTime});
              current.reported=true;record(this,'progress',current);
            }
            current.lastTime=this.currentTime;
          });
          for(const event of ['error','waiting','stalled','emptied'])this.addEventListener(event,()=>{
            const current=generations.get(this);if(current)record(this,event,current);
          });
        }
        record(this,'play',generation);
        const current=generation,result=play.apply(this,args);
        // Snapshot this native generation after its play promise and Svelte's
        // pending render flush. Later timeupdates never follow arbitrary labels.
        void result.then(()=>queueMicrotask(()=>{
          if(generations.get(this)!==current||this.src!==current.source||current.epoch<1||sourceKind(current.source)!=='stored_blob')return;
          const candidate=document.querySelector('[data-testid="assistant-speech-waveform"]')?.getAttribute('data-segment-id');
          const ready=(window as unknown as {__voiceCallEvidence?:CallEvidence}).__voiceCallEvidence?.received.some(frame=>
            frame.type==='assistant_speech_status'&&frame.speechStatus==='ready'&&frame.segmentId===candidate&&!!frame.generatedAssetId);
          if(!candidate||!ready)return;
          const known=storedBindings.get(current.source);
          if(known===null||known&&known!==candidate){storedBindings.set(current.source,null);return;}
          storedBindings.set(current.source,candidate);current.segmentId=candidate;
        })).catch(()=>{});
        return result;
      };
      Object.assign(window,{__voiceManualSpeechPlayback:state,__voiceManualSpeechDownloads:new Map<string,string>()});
    });
    await observeSpeechMediaSources(page);
    await installNativeVoiceInput(page);await observeRealTransport(page);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await playNativeVoiceFixture(page);await waitForSpokenAssistant(page);
    const assistant=page.getByTestId('message-assistant').filter({hasText:ASSISTANT_SPEECH});
    await expect(assistant).toHaveCount(1);
    const messageId=(await assistant.getAttribute('data-message-id'))!;
    const chatId=voiceFrames(await evidence(page),'start')[0].chatId!;
    const player=page.getByTestId('assistant-speech-player');
    await expect(player).toHaveCount(0);
    await expect(assistant.getByTestId('assistant-message-speak')).toHaveCount(0);
    await expect.poll(async()=>(await evidence(page)).received.some(frame=>frame.type==='assistant_speech_audio'
      &&frame.messageId===messageId&&frame.kind==='voice_prose_turn'&&frame.streamPhase==='end'),{timeout:60_000}).toBe(true);
    const callProof=await evidence(page);
    const callTracks=[...new Set(callProof.received.filter(frame=>frame.type==='assistant_speech_audio'
      &&frame.messageId===messageId&&frame.kind==='voice_prose_turn').map(frame=>frame.segmentId!))];
    expect(callTracks).toHaveLength(1);
    const callAttempts=callProof.received.filter(frame=>frame.type==='assistant_speech_audio'
      &&frame.messageId===messageId&&frame.kind==='voice_prose_turn');
    expect(new Set(callAttempts.map(frame=>frame.attemptId)).size).toBe(1);
    expect(callAttempts.every(frame=>frame.sequence===0&&!!frame.attemptId)).toBe(true);
    expect(callAttempts.filter(frame=>frame.streamPhase==='start')).toHaveLength(1);
    expect(new Set(callAttempts.map(frame=>frame.sourceVersion)).size).toBe(1);
    expect(new Set(callAttempts.map(frame=>frame.executionVersion)).size).toBe(1);
    await expect.poll(()=>page.evaluate(segments=>new Set((window as unknown as {__voiceManualSpeechPlayback:{ended:Array<{trackId:string;observedAt:number}>}})
      .__voiceManualSpeechPlayback.ended.filter(item=>segments.includes(item.trackId)).map(item=>item.trackId)).size,callTracks),{timeout:60_000}).toBe(callTracks.length);
    const drainedAt=callAttempts.find(frame=>frame.streamPhase==='end')!.observedAt!;
    const nativeEndedAt=await page.evaluate(trackId=>(window as unknown as {__voiceManualSpeechPlayback:{ended:Array<{trackId:string;observedAt:number}>}})
      .__voiceManualSpeechPlayback.ended.find(item=>item.trackId===trackId)?.observedAt,callTracks[0]);
    expect(nativeEndedAt).toBeGreaterThanOrEqual(drainedAt);
    await expect(player).toHaveCount(0);
    await expect(assistant.getByTestId('assistant-message-speak')).toHaveCount(0);
    expect(callProof.received.filter(frame=>frame.type==='assistant_speech_status'&&frame.messageId===messageId&&frame.generatedAssetPresent)).toHaveLength(0);
    await expect.poll(()=>page.evaluate(segments=>(window as unknown as {__voiceManualSpeechPlayback:{progress:Array<{epoch:number;segmentId:string|null;sourceKind:string;currentTime:number}>}})
      .__voiceManualSpeechPlayback.progress.some(item=>item.epoch===0&&item.sourceKind==='mse'&&item.currentTime>0&&segments.includes(item.segmentId??'')),callTracks)).toBe(true);
    await page.getByTestId('voice-call-hangup').click();await assertVoiceInputCleanup(page);
    const speak=assistant.getByTestId('assistant-message-speak');
    expect(speechCapabilityResponses).toBeGreaterThan(0);
    await expect(speak).toBeVisible();
    const startManual=(await evidence(page)).received.length;
    await page.evaluate(()=>(window as unknown as {__voiceManualSpeechPlayback:{epoch:number}}).__voiceManualSpeechPlayback.epoch=1);
    await clickChatTarget(speak,testInfo);
    await expect.poll(async()=>(await evidence(page)).received.slice(startManual).some(frame=>frame.type==='assistant_speech_status'
      &&frame.messageId===messageId&&frame.speechStatus==='ready'&&frame.generatedAssetId),{timeout:60_000}).toBe(true);
    await expect(player).toHaveAttribute('data-status','completed',{timeout:60_000});
    const manual=(await evidence(page)).received.slice(startManual).filter(frame=>frame.type==='assistant_speech_status'
      &&frame.messageId===messageId&&frame.speechStatus==='ready'&&frame.generatedAssetId);
    const assets=[...new Set(manual.map(frame=>frame.generatedAssetId!))].sort();
    expect(assets.length).toBeGreaterThan(0);
    expect(manual.every(frame=>!!frame.segmentId&&!callTracks.includes(frame.segmentId))).toBe(true);
    const manualSegments=[...new Set(manual.map(frame=>frame.segmentId!))];
    expect((await evidence(page)).received.slice(startManual).filter(frame=>frame.type==='assistant_speech_audio'&&frame.messageId===messageId)).toHaveLength(0);
    await expect.poll(()=>page.evaluate(segments=>(window as unknown as {__voiceManualSpeechPlayback:{progress:Array<{epoch:number;segmentId:string|null;sourceKind:string;currentTime:number}>}})
      .__voiceManualSpeechPlayback.progress.some(item=>item.epoch===1&&item.sourceKind==='stored_blob'&&item.currentTime>0&&segments.includes(item.segmentId??'')),manualSegments)).toBe(true);
    const apiUrl=process.env.PLAYWRIGHT_TEST_API_URL;expect(apiUrl).toBeTruthy();
    const access=async(assetId:string,remember:boolean)=>page.evaluate(async({apiUrl,assetId,remember})=>{
      const saved=(window as unknown as {__voiceManualSpeechDownloads:Map<string,string>}).__voiceManualSpeechDownloads;
      const metadata=await fetch(`${apiUrl}/v1/generated-assets/${assetId}/files/original/download-url`,{credentials:'include',cache:'no-store'});
      if(remember&&metadata.ok){
        const body=await metadata.json();
        const url=new URL(body.download_url,apiUrl);
        if(url.origin!==new URL(apiUrl).origin||url.pathname!==`/v1/generated-assets/${assetId}/files/original/download`)throw new Error('Unexpected generated audio route');
        saved.set(assetId,url.href);
      }
      const url=saved.get(assetId);if(!url)throw new Error('Generated audio download was not observed');
      const audio=await fetch(url,{credentials:'include',cache:'no-store'});
      await audio.body?.cancel();
      // Only status codes leave the browser; signed URLs and bytes stay private.
      return {metadata:metadata.status,audio:audio.status};
    },{apiUrl:apiUrl!,assetId,remember});
    for(const assetId of assets)expect(await access(assetId,true)).toEqual({metadata:200,audio:200});
    await player.getByTestId('assistant-speech-close').click();
    const startReplay=(await evidence(page)).received.length;
    await page.evaluate(()=>(window as unknown as {__voiceManualSpeechPlayback:{epoch:number}}).__voiceManualSpeechPlayback.epoch=2);
    await clickChatTarget(speak,testInfo);
    await expect.poll(async()=>(await evidence(page)).received.slice(startReplay).some(frame=>frame.type==='assistant_speech_status'
      &&frame.messageId===messageId&&frame.speechStatus==='ready'&&frame.generatedAssetId),{timeout:30_000}).toBe(true);
    await expect(player).toHaveAttribute('data-status','completed',{timeout:60_000});
    const replay=(await evidence(page)).received.slice(startReplay).filter(frame=>frame.type==='assistant_speech_status'&&frame.messageId===messageId);
    expect([...new Set(replay.filter(frame=>frame.speechStatus==='ready').map(frame=>frame.generatedAssetId!))].sort()).toEqual(assets);
    expect(replay.filter(frame=>['queued','generating'].includes(frame.speechStatus??''))).toHaveLength(0);
    await expect.poll(()=>page.evaluate(segments=>(window as unknown as {__voiceManualSpeechPlayback:{progress:Array<{epoch:number;segmentId:string|null;sourceKind:string;currentTime:number}>}})
      .__voiceManualSpeechPlayback.progress.some(item=>item.epoch===2&&item.sourceKind==='stored_blob'&&item.currentTime>0&&segments.includes(item.segmentId??'')),manualSegments)).toBe(true);
    await player.getByTestId('assistant-speech-close').click();
    const sidebar=page.locator('.sidebar');
    if(await sidebar.evaluate(element=>element.classList.contains('closed')))await page.getByTestId('sidebar-toggle').click();
    const row=page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
    await expect(row).toBeVisible();await row.click({button:'right'});
    const remove=page.getByTestId('chat-context-delete');await remove.click();await remove.click();
    await expect.poll(async()=>(await evidence(page)).received.some(frame=>frame.type==='chat_deleted'&&frame.chatId===chatId&&frame.tombstone),{timeout:30_000}).toBe(true);
    await expect(row).toHaveCount(0);
    for(const assetId of assets)await expect.poll(()=>access(assetId,false),{timeout:45_000,intervals:[1000,2000,3000]}).toEqual({metadata:404,audio:404});
    // Normal owner metadata and the previously minted audio URL are revoked.
    // Physical S3 object deletion is covered by backend cleanup/fault tests.
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


  // contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission,video-call.privacy,assistant-speech.playback.live-call-streaming,ai-model-routing.preprocessing.prepared-privacy
  test('keeps continuous playback progress conservative on interruption while retaining the complete rich answer',async({page},testInfo)=>{
    await installVoiceFixtureImageProxy(page);
    test.setTimeout(180_000);
    await page.addInitScript(()=>{
      const audio=new Set<HTMLMediaElement>();
      const held:HeldSpeechEvidence={audio:null,segmentId:null,source:null,offset:0,firstProgressAt:null,
        playCallsAtHold:0,playCalls:0,sourceMse:false,beforeProviderEnd:false,sequence:null,nativeErrors:[]};
      const mseUrls=new Set<string>();
      const createObjectURL=URL.createObjectURL.bind(URL);
      URL.createObjectURL=object=>{
        const url=createObjectURL(object);
        if(object instanceof MediaSource)mseUrls.add(url);
        return url;
      };
      const calls=new WeakMap<HTMLMediaElement,Map<string,number>>();
      Object.assign(window,{__voiceSpeechPlayback:audio,__voiceSpeechHeld:held});
      const play=HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play=function(...args:Parameters<HTMLMediaElement['play']>){
        const perSource=calls.get(this)??new Map<string,number>();calls.set(this,perSource);
        perSource.set(this.src,(perSource.get(this.src)??0)+1);
        if(held.audio===this)held.playCalls++;
        if(!audio.has(this)) {
          audio.add(this);
          this.addEventListener('error',()=>{
            held.nativeErrors.push({code:this.error?.code??0,observedAt:performance.now()});
          });
          let lastSource=this.src;let lastTime=0;
          this.addEventListener('timeupdate',()=>{
            if(lastSource!==this.src){lastSource=this.src;lastTime=0;}
            const advancing=this.currentTime>lastTime+0.001;lastTime=this.currentTime;
            if(held.audio===this&&this.src!==held.source&&mseUrls.has(this.src)&&!this.paused&&!this.ended&&advancing){
              const active=(window as unknown as {__voiceSpeechMediaSources:Map<string,string>}).__voiceSpeechMediaSources.get(this.src);
              const evidence=(window as unknown as {__voiceCallEvidence?:CallEvidence}).__voiceCallEvidence;
              const next=evidence?.received.find(frame=>frame.type==='assistant_speech_audio'&&frame.streamPhase==='chunk'
                &&frame.kind==='voice_prose_turn'&&frame.segmentId===active&&frame.messageId===evidence.heldSpeechAudio?.messageId);
              if(next?.messageId&&active&&!held.handoffProgress)held.handoffProgress={messageId:next.messageId,segmentId:active,
                audioId:(window as unknown as {__nativeVoiceInput:NativeVoiceInputEvidence}).__nativeVoiceInput.speechAudioId(this),
                observedAt:performance.now(),currentTime:this.currentTime};
            }
            if(held.audio||!(this instanceof HTMLAudioElement)||!mseUrls.has(this.src)||this.paused||this.ended||this.currentTime<=0)return;
            const active=(window as unknown as {__voiceSpeechMediaSources:Map<string,string>}).__voiceSpeechMediaSources.get(this.src);
            const evidence=(window as unknown as {__voiceCallEvidence?:CallEvidence}).__voiceCallEvidence;
            const prose=evidence?.received.find(frame=>frame.type==='assistant_speech_audio'&&frame.kind==='voice_prose_turn'
              &&frame.streamPhase==='chunk'&&frame.segmentId===active);
            const ended=evidence?.received.some(frame=>frame.type==='assistant_speech_audio'&&frame.streamPhase==='end'&&frame.segmentId===active);
            if(!prose||!active||ended)return;
            // Preserve a real heard offset and the actual clip. Native pause
            // prevents playback finishing while canonical finalization runs.
            held.audio=this;held.segmentId=active;held.offset=this.currentTime;
            held.source=this.src;held.sourceMse=true;held.beforeProviderEnd=true;held.firstProgressAt=performance.now();
            held.sequence=prose.sequence??null;
            held.playCallsAtHold=perSource.get(this.src)??0;held.playCalls=held.playCallsAtHold;
            this.pause();
          });
        }
        return play.apply(this,args);
      };
    });
    await observeSpeechMediaSources(page);
    await installNativeVoiceInput(page);await observeRealTransport(page);
    await loginToTestAccount(page,()=>{},async()=>{},{waitForEditor:false});
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await page.getByTestId('voice-call-mute').click();
    const richTurnId=await sendCameraCallText(page,'Show voice rich results');
    await expect(page.getByTestId('assistant-speech-player')).toHaveCount(0);
    await expect(page.getByTestId('assistant-message-speak')).toHaveCount(0);
    const editor=page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await expect(editor).toBeEmpty();await editor.click();
    const followup='Please continue from the last part I heard.';
    await page.keyboard.insertText(followup);
    await page.waitForFunction(()=>{
      const held=(window as unknown as {__voiceSpeechHeld:HeldSpeechEvidence}).__voiceSpeechHeld;
      return !!held.audio&&held.audio.paused&&!held.audio.ended&&held.offset>0;
    },undefined,{timeout:60_000,polling:'raf'});
    // The entire produced rich answer must precede interruption. Keep the same
    // genuinely advanced prose clip available across canonical finalization.
    await waitForCanonicalAssistant(page,richTurnId);
    await page.waitForFunction(()=>{
      const browser=window as unknown as {__voiceCallEvidence:CallEvidence;__voiceSpeechHeld:HeldSpeechEvidence};
      return browser.__voiceCallEvidence.received.some(frame=>frame.type==='assistant_speech_audio'
        &&frame.streamPhase==='end'&&frame.segmentId===browser.__voiceSpeechHeld.segmentId);
    },undefined,{timeout:45_000});
    const progressive=await page.evaluate(userTurnId=>{
      const browser=window as unknown as {__voiceCallEvidence:CallEvidence;__voiceSpeechHeld:HeldSpeechEvidence;
        __nativeVoiceInput:NativeVoiceInputEvidence};
      const held=browser.__voiceSpeechHeld;
      const end=browser.__voiceCallEvidence.received.find(frame=>frame.type==='assistant_speech_audio'
        &&frame.streamPhase==='end'&&frame.segmentId===held.segmentId);
      return {audioId:held.audio?browser.__nativeVoiceInput.speechAudioId(held.audio):null,
        mse:held.sourceMse,beforeProviderEnd:held.beforeProviderEnd,firstProgressAt:held.firstProgressAt,
        providerEndAt:end?.observedAt,canonicalFinalAt:browser.__voiceCallEvidence.received.find(frame=>
          frame.type==='ai_message_update'&&frame.userMessageId===userTurnId&&frame.final)?.observedAt,sourceUnchanged:held.audio?.src===held.source,
        offsetPreserved:Math.abs((held.audio?.currentTime??0)-held.offset)<0.01,
        paused:held.audio?.paused,playCallsAtHold:held.playCallsAtHold,playCalls:held.playCalls,
        assets:browser.__voiceCallEvidence.received.filter(frame=>frame.type==='assistant_speech_status'
          &&frame.generatedAssetPresent).length};
    },richTurnId);
    expect(progressive).toMatchObject({mse:true,beforeProviderEnd:true,sourceUnchanged:true,offsetPreserved:true,paused:true,
      playCallsAtHold:1,playCalls:1,assets:0});
    expect(progressive.firstProgressAt).not.toBeNull();
    expect(progressive.audioId).not.toBeNull();
    const speechRegistration=(await evidence(page)).sent.find(frame=>frame.type==='voice_call_chat_prepare');
    expect(speechRegistration).toBeTruthy();
    await assertSpeechAutoplayPrimed(page,speechRegistration!.observedAt!,progressive.audioId!);
    await testInfo.attach('voice-native-speech-prime-and-progress',{body:JSON.stringify({
      primes:(await nativeVoiceInput(page)).speechPrimes,registrationAt:speechRegistration!.observedAt,progressive,
    }),contentType:'application/json'});
    expect(progressive.providerEndAt).toBeGreaterThan(progressive.firstProgressAt!);
    expect(progressive.canonicalFinalAt).toBeDefined();
    expect(progressive.canonicalFinalAt!).toBeGreaterThan(progressive.firstProgressAt!);
    // The rich response has multiple immutable clauses but one encoded MP3
    // track, one provider attempt and one native source. Never relabel it as
    // independently ended clause files or use the hidden message player as proof.
    const continuousProof=await page.evaluate(()=>{
      const browser=window as unknown as {__voiceCallEvidence:CallEvidence;__voiceSpeechHeld:HeldSpeechEvidence;
        __voiceSpeechMediaSources:Map<string,string>};
      const trackId=browser.__voiceSpeechHeld.segmentId!;
      const frames=browser.__voiceCallEvidence.received.filter(frame=>frame.type==='assistant_speech_audio'
        &&frame.segmentId===trackId&&frame.kind==='voice_prose_turn');
      const messageId=frames[0]?.messageId;
      const members=browser.__voiceCallEvidence.received.filter(frame=>frame.type==='assistant_speech_status'
        &&frame.messageId===messageId&&frame.kind==='voice_prose_clause'&&frame.speechStatus==='sealed');
      return {trackId,messageId,frames,members,
        nativeSourceCount:[...browser.__voiceSpeechMediaSources].filter(([,id])=>id===trackId).length,
        sourceMatchesHeld:browser.__voiceSpeechMediaSources.get(browser.__voiceSpeechHeld.source??'')===trackId,
        alignmentEvents:frames.filter(frame=>frame.streamPhase==='alignment').length,
        finiteProseAudio:browser.__voiceCallEvidence.received.filter(frame=>frame.type==='assistant_speech_audio'
          &&frame.messageId===messageId&&frame.kind==='voice_prose_clause').length};
    });
    expect(continuousProof.frames.filter(frame=>frame.streamPhase==='start')).toHaveLength(1);
    expect(continuousProof.frames.filter(frame=>frame.streamPhase==='end')).toHaveLength(1);
    expect(continuousProof.frames.every(frame=>frame.sequence===0&&!!frame.attemptId)).toBe(true);
    expect(new Set(continuousProof.frames.map(frame=>frame.attemptId)).size).toBe(1);
    expect(new Set(continuousProof.frames.map(frame=>frame.sourceVersion)).size).toBe(1);
    expect(new Set(continuousProof.frames.map(frame=>frame.executionVersion)).size).toBe(1);
    expect(continuousProof.nativeSourceCount).toBe(1);expect(continuousProof.sourceMatchesHeld).toBe(true);
    expect(continuousProof.members.length).toBeGreaterThanOrEqual(2);
    expect(continuousProof.members.every(frame=>!!frame.segmentId&&frame.segmentId!==continuousProof.trackId
      &&frame.turnTrackId===continuousProof.trackId&&frame.sourceVersion===continuousProof.frames[0].sourceVersion)).toBe(true);
    expect(new Set(continuousProof.members.map(frame=>frame.segmentId)).size).toBe(continuousProof.members.length);
    expect(continuousProof).toMatchObject({alignmentEvents:0,finiteProseAudio:0});
    await testInfo.attach('voice-continuous-track-and-immutable-clauses',{body:JSON.stringify(continuousProof),contentType:'application/json'});
    await page.evaluate(async()=>{
      const held=(window as unknown as {__voiceSpeechHeld:HeldSpeechEvidence}).__voiceSpeechHeld;
      await held.audio!.play();
    });
    await page.waitForFunction(()=>{
      const browser=window as unknown as {__voiceCallEvidence:CallEvidence;
        __voiceSpeechHeld:HeldSpeechEvidence};
      const held=browser.__voiceSpeechHeld;
      const active=(window as unknown as {__voiceSpeechMediaSources:Map<string,string>}).__voiceSpeechMediaSources.get(held.audio?.src??'');
      const voice=browser.__voiceCallEvidence.received.some(frame=>frame.type==='assistant_speech_audio'&&frame.kind==='voice_prose_turn'&&frame.streamPhase==='chunk'&&frame.segmentId===active);
      return voice&&active===held.segmentId&&held.audio?.src===held.source&&!held.audio.paused&&!held.audio.ended&&held.audio.currentTime>held.offset;
    },undefined,{timeout:10_000,polling:'raf'});
    // Phase3 always supplies a genuine authenticated batch, including an empty
    // batch for an empty account. Require that real source; never fabricate one.
    await page.waitForFunction(()=>{
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      return !!state.memoryBatch&&state.memoryBatch.socketId===state.mainSocketId&&typeof state.replayMemoryBatch==='function';
    },undefined,{timeout:10_000});
    const before=voiceFrames(await evidence(page),'text_input').length;
    const previousMessageId=await page.getByTestId('message-assistant').filter({hasText:'Here are the images I found.'}).getAttribute('data-message-id');
    expect(previousMessageId).toBeTruthy();
    const boundChatId=voiceFrames(await evidence(page),'start')[0].chatId!;
    await page.evaluate(({chatId,previousMessageId})=>{
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      state.holdSpeechResponse={chatId,previousMessageId};state.holdPrivacySnapshot=true;
    },{chatId:boundChatId,previousMessageId:previousMessageId!});
    try{
    await page.getByTestId('composer-send-button').click();
    await expect.poll(async()=>voiceFrames(await evidence(page),'text_input').length).toBe(before+1);
    const nextId=voiceFrames(await evidence(page),'text_input').at(-1)!.messageId!;
    await page.waitForFunction(()=>!!(window as unknown as {__voiceCallEvidence:CallEvidence})
      .__voiceCallEvidence.privacySnapshotHeld,undefined,{timeout:10_000});
    const privacyHeld=await page.evaluate(()=>{
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      return {held:state.privacySnapshotHeld,sameConnection:state.privacySnapshotHeld?.socketId===state.mainSocketId};
    });
    expect(privacyHeld.held?.success).toBe(true);expect(privacyHeld.sameConnection).toBe(true);
    expect(privacyHeld.held?.releasedAt).toBeUndefined();
    await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.replayMemoryBatch!());
    await page.waitForFunction(()=>{
      const replay=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.privacyNoopReplay;
      return replay?.producerAt!==undefined;
    },undefined,{timeout:5000});
    const privacyNoop=await page.evaluate(()=>{
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      return {held:state.privacySnapshotHeld,replay:state.privacyNoopReplay};
    });
    expect(privacyNoop.replay?.producerUnchanged,'the genuine unchanged batch must emit the production no-write proof').toBe(true);
    expect(privacyNoop.held?.releasedAt).toBeUndefined();
    expect(privacyNoop.replay!.replayedAt).toBeGreaterThanOrEqual(privacyNoop.held!.heldAt);
    expect(privacyNoop.replay!.producerAt!).toBeGreaterThanOrEqual(privacyNoop.replay!.replayedAt);
    await testInfo.attach('voice-privacy-noop-during-fresh-send',{body:JSON.stringify(privacyNoop),contentType:'application/json'});
    await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.releasePrivacySnapshot!());
    await expect.poll(async()=>(await evidence(page)).sent.find(frame=>frame.type==='chat_message_added'&&frame.messageId===nextId)?.heardBoundary,{timeout:45_000}).toBeTruthy();
    const protocol=await evidence(page);
    const privacyOrder=await page.evaluate(() => {
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      return {producerAt:state.privacyNoopReplay?.producerAt,releasedAt:state.privacySnapshotHeld?.releasedAt};
    });
    expect(privacyOrder.releasedAt).toBeDefined();
    expect(privacyOrder.producerAt!).toBeLessThanOrEqual(privacyOrder.releasedAt!);
    expect(protocol.sent.find(frame=>frame.type==='chat_message_added'&&frame.messageId===nextId)!.observedAt!)
      .toBeGreaterThan(privacyOrder.releasedAt!);
    const boundary=protocol.sent.find(frame=>frame.type==='chat_message_added'&&frame.messageId===nextId)!.heardBoundary!;
    const prior=page.getByTestId('message-assistant').filter({hasText:'Here are the images I found.'});
    await expect(prior).toHaveCount(1);
    expect(boundary.assistant_message_id).toBe(await prior.getAttribute('data-message-id'));
    // This provider fixture supplies no verified alignment. Real audible track
    // progress is proved above, but track sequence zero is never prose clause zero.
    // Provider completion while native playback is paused grants no heard clauses.
    expect(boundary).toEqual({assistant_message_id:await prior.getAttribute('data-message-id'),
      completed_sequences:[],active_sequence:null,active_offset_ms:0});
    const heldTrack=await page.evaluate(()=>{
      const held=(window as unknown as {__voiceSpeechHeld:HeldSpeechEvidence}).__voiceSpeechHeld;
      return {trackSequence:held.sequence,offsetMs:Math.floor(held.offset*1000)};
    });
    expect(heldTrack.trackSequence).toBe(0);expect(heldTrack.offsetMs).toBeGreaterThan(0);
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
    await page.waitForFunction(()=>{
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      const next=state.heldSpeechAudio;
      return !!next&&next.count>0&&state.received.some(frame=>frame.type==='assistant_speech_status'
        &&frame.messageId===next.messageId&&frame.speechStatus==='queued');
    },undefined,{timeout:45_000});
    const handoff=await page.evaluate(async()=>{
      // Let native load/error tasks settle while genuine next audio stays held.
      await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
      const browser=window as unknown as {__voiceCallEvidence:CallEvidence;__voiceSpeechHeld:HeldSpeechEvidence};
      const audio=browser.__voiceSpeechHeld.audio!;
      return {held:browser.__voiceCallEvidence.heldSpeechAudio,hasSourceAttribute:audio.hasAttribute('src'),
        networkEmpty:audio.networkState===HTMLMediaElement.NETWORK_EMPTY,errorCode:audio.error?.code??null,
        nativeErrors:browser.__voiceSpeechHeld.nativeErrors,
        nextStreamDelivered:browser.__voiceCallEvidence.received.some(frame=>frame.type==='assistant_speech_audio'
          &&frame.messageId===browser.__voiceCallEvidence.heldSpeechAudio?.messageId)};
    });
    expect(handoff.held!.count).toBeGreaterThan(0);
    expect(handoff).toMatchObject({hasSourceAttribute:false,networkEmpty:true,errorCode:null,nativeErrors:[],nextStreamDelivered:false});
    await testInfo.attach('voice-native-response-handoff',{body:JSON.stringify(handoff),contentType:'application/json'});
    await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.releaseSpeechAudio!());
    await page.waitForFunction(()=>{
      const browser=window as unknown as {__voiceCallEvidence:CallEvidence;__voiceSpeechHeld:HeldSpeechEvidence};
      return browser.__voiceSpeechHeld.handoffProgress?.messageId===browser.__voiceCallEvidence.heldSpeechAudio?.messageId
        &&!!browser.__voiceSpeechHeld.handoffProgress;
    },undefined,{timeout:30_000,polling:'raf'});
    const secondPlayback=await page.evaluate(()=>{
      const browser=window as unknown as {__voiceSpeechHeld:HeldSpeechEvidence;__voiceCallEvidence:CallEvidence};
      const held=browser.__voiceSpeechHeld;const state=browser.__voiceCallEvidence;
      return {progress:held.handoffProgress,nativeErrors:held.nativeErrors,releasedAt:state.heldSpeechAudio?.releasedAt,
        streamStartAt:state.received.find(frame=>frame.type==='assistant_speech_audio'&&frame.streamPhase==='start'
          &&frame.segmentId===held.handoffProgress?.segmentId&&frame.messageId===held.handoffProgress?.messageId)?.observedAt};
    });
    expect(secondPlayback.progress!.audioId).toBe(progressive.audioId);
    expect(secondPlayback.progress!.currentTime).toBeGreaterThan(0);expect(secondPlayback.nativeErrors).toEqual([]);
    expect(secondPlayback.releasedAt).toBeDefined();expect(secondPlayback.streamStartAt).toBeDefined();
    expect(secondPlayback.streamStartAt!).toBeGreaterThanOrEqual(secondPlayback.releasedAt!);
    expect(secondPlayback.progress!.observedAt).toBeGreaterThan(secondPlayback.streamStartAt!);
    await testInfo.attach('voice-native-second-response-progress',{body:JSON.stringify(secondPlayback),contentType:'application/json'});
    await waitForCanonicalAssistant(page,nextId);
    await expect(page.getByTestId('message-assistant').filter({hasText:'I received your text: '+followup})).toHaveCount(1);
    await page.getByTestId('voice-call-hangup').click();await assertVoiceInputCleanup(page);
    expect(await page.evaluate(()=>(window as unknown as {__voiceSpeechHeld:HeldSpeechEvidence}).__voiceSpeechHeld.nativeErrors)).toEqual([]);
    }finally{
      await page.evaluate(()=>{
        const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
        delete state.holdPrivacySnapshot;state.releasePrivacySnapshot?.();
        delete state.holdSpeechResponse;state.releaseSpeechAudio?.();
      }).catch(()=>{});
    }
  });

});
