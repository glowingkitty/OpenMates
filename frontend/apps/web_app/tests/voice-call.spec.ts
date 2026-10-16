/**
 * Real first-party call transport and encrypted chat persistence in isolated CI.
 * Only the external voice provider is synthetic, gated inside the disposable
 * backend; browser sockets, session admission and message storage stay real.
 */
import type { Locator, Page } from '@playwright/test';
import { scrollChatHistoryToStart, waitForStickyCallControlsReady } from './helpers/chat-scroll';
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, waitForChatReady, startNewChat, sendMessage, waitForAssistantMessage } = require('./helpers/chat-test-helpers');
const { withMockMarker } = require('./signup-flow-helpers');
const USER_SPEECH = 'How do I make ramen?';
const ASSISTANT_SPEECH = 'For ramen, simmer the broth and cook the noodles.';
const STAGE_TWO_TEXT = 'Voice stage two fixture: apply memory and search the web';
const STAGE_TWO_REPLY = 'Your approved memory is loaded and the search results are ready.';
const CHECKPOINT_FACT = 'The recipe must remain vegetarian and use ginger.';
const UNCOVERED_CONTEXT_FACT = 'The oldest uncovered turn requires sesame-free toppings.';
const ACTIVITY_REQUEST = 'Hold this voice activity reply until I speak again.';
const ACTIVITY_REPLY = 'Your voice activity fixture reply is ready.';
const PASTED_TEXT = 'Please use this pasted recipe: noodles, broth, mushrooms and ginger.';

interface SocketObservation {
  path: string;
  code?: string;
  stage?: string;
  socketId?: number;
  type: string;
  observedAt?: number;
  audioSamples?: number;
  audioBatch?: number;
  audioNonzero?: boolean;
  startupAllowanceMs?: number;
  messageId?: string;
  chatId?: string;
  callId?: string;
  role?: string;
  assistantMessageId?: string;
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
interface CallEvidence {
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
  chatLookupDiagnostics?: {
    selectedConstructors: number;
    omittedConstructors: number;
    promises: Array<{ ordinal: number; resolutionRequests: number; rejectionRequests: number;
      matchedBoundRow: boolean; held: boolean }>;
  };
  releaseChatLookup?: () => void;
}

test.use({
  actionTimeout: 30_000,
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status === testInfo.expectedStatus) return;
  try {
    const runtime = await page.evaluate(() => {
      const browser = window as unknown as { __voiceCallEvidence?: CallEvidence;
        __nativeVoiceInput?: NativeVoiceInputEvidence; __voicePrivacyEvents?: string[] };
      const transport = browser.__voiceCallEvidence;
      const native = browser.__nativeVoiceInput;
      const privacy = browser.__voicePrivacyEvents ?? [];
      const sent = transport?.sent.filter(frame => frame.path === '/v1/voice-call') ?? [];
      const received = transport?.received.filter(frame => frame.path === '/v1/voice-call') ?? [];
      return {
        transportObserved: !!transport,
        nativeCaptureObserved: !!native,
        privacyBoundaryObserved: Array.isArray(browser.__voicePrivacyEvents),
        voiceSocketRequests: privacy.filter(event => event === 'voice_socket').length,
        voiceStartFrames: sent.filter(frame => frame.type === 'start').length,
        voiceReadyFrames: received.filter(frame => frame.type === 'ready').length,
        voiceMicFrames: sent.filter(frame => frame.type === 'mic_audio').length,
        voiceEndFrames: sent.filter(frame => frame.type === 'audio_stream_end').length,
        mainSocketOpen: transport?.mainSocket?.readyState === WebSocket.OPEN,
        microphoneRequests: privacy.filter(event => event === 'microphone_requested').length,
        capturesResolved: native?.captureRequests ?? 0,
        nativeLiveTracks: native?.nativeTracks.filter(track => track.readyState === 'live').length ?? 0,
        outputLiveTracks: native?.outputTracks.filter(track => track.readyState === 'live').length ?? 0,
        contextsRunning: native?.contexts.filter(context => context.state === 'running').length ?? 0,
        contextsSuspended: native?.contexts.filter(context => context.state === 'suspended').length ?? 0,
        contextsClosed: native?.contexts.filter(context => context.state === 'closed').length ?? 0,
        workersCreated: native?.workersCreated ?? 0,
        workersReady: native?.detectorReady ?? 0,
        workersTerminated: native?.workersTerminated ?? 0,
        acknowledgementReads: privacy.filter(event => event === 'ack_get').length,
        acknowledgementWrites: privacy.filter(event => event === 'ack_post').length,
        acknowledgementsSaved: privacy.filter(event => event === 'ack_saved').length,
      };
    });
    await testInfo.attach('voice-runtime-diagnostic', { body: JSON.stringify(runtime), contentType: 'application/json' });
  } catch {
    await testInfo.attach('voice-runtime-diagnostic', { body: JSON.stringify({ captureFailed: true }), contentType: 'application/json' });
  }
  try {
    // Failure evidence contains only counts/booleans/lengths. Browser keys,
    // transcript text, source IDs and ciphertext never leave this evaluation.
    const diagnostic = await page.evaluate(async (expectedReply) => {
      const state = (window as unknown as { __voiceCallEvidence?: CallEvidence }).__voiceCallEvidence;
      if (!state) return { transportObserved: false };
      const callId = state.received.filter((event) => event.type === 'ready').at(-1)?.callId;
      const compression = state.received.filter((event) => event.type === 'voice_compression' && event.callId === callId).at(-1);
      const targetIds = [...new Set(state.received.filter((event) => event.type === 'voice_embed' && event.callId === callId)
        .map((event) => event.assistantMessageId).filter((id): id is string => !!id))];
      const phaseCounts = Object.fromEntries(['voice_compression_started', 'voice_compression', 'chat_compression_checkpoint_stored',
        'voice_context_pause', 'voice_context_resumed'].map((type) => [type, state.received.filter((event) => event.type === type).length]));
      const open = (name: string) => new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open(name); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      const read = <T>(db: IDBDatabase, store: string, id: string) => new Promise<T>((resolve, reject) => {
        const request = db.transaction(store, 'readonly').objectStore(store).get(id);
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      const database = await open('chats_db');
      const cryptoDatabase = await open('openmates_crypto');
      try {
        const masterKey = await read<CryptoKey>(cryptoDatabase, 'keys', 'master_key');
        const rows = [];
        for (const id of targetIds) {
          const row = await read<{ chat_id: string; created_at: number; queue_revision?: number; encrypted_content?: string;
            content?: string; call_persistence_v1?: { call_id: string; entries: unknown[] } } | undefined>(database, 'messages', id);
          const frames = state.received.filter((event) => event.type === 'transcript' && event.messageId === id);
          let decryptable = false;
          let expectedTextStored = false;
          let storedTextLength = 0;
          if (row?.encrypted_content && masterKey) {
            try {
              const chat = await read<{ encrypted_chat_key: string }>(database, 'chats', row.chat_id);
              const bytes = (value: string) => Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
              const wrapped = bytes(chat.encrypted_chat_key);
              const rawKey = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: wrapped.slice(0, 12) }, masterKey, wrapped.slice(12));
              const text = await state.decryptChatContent!(row.encrypted_content, rawKey);
              decryptable = true; expectedTextStored = text.includes(expectedReply); storedTextLength = text.length;
            } catch { /* Record a boolean, never private decryption error data. */ }
          }
          rows.push({ localRowExists: !!row, decryptable, expectedTextStored, storedTextLength,
            revision: row?.queue_revision ?? 0, pendingCiphertexts: row?.call_persistence_v1?.entries.length ?? 0,
            plaintextStored: typeof row?.content === 'string', originMatchesCall: row?.call_persistence_v1?.call_id === callId,
            coveredByLatestCheckpoint: compression?.coveredMessageIds?.includes(id) ?? false,
            atOrBeforeLatestBoundary: !!row && !!compression?.boundaryTimestamp && row.created_at <= compression.boundaryTimestamp,
            transcriptFrames: frames.length, expectedTextFrames: frames.filter((event) => event.expectedReply).length,
            finalExpectedTextFrames: frames.filter((event) => event.final && event.expectedReply).length,
            maxTranscriptLength: Math.max(0, ...frames.map((event) => event.textLength ?? 0)) });
        }
        return { transportObserved: true, phaseCounts, targetRowCount: targetIds.length, rows,
          errors: state.received.filter(event => event.type === 'error').map(({code, stage}) => ({code, stage})),
          contextShape: state.sent.find(event => event.type === 'start')?.context?.map(row => ({
            role: row.role === 'user' || row.role === 'assistant' ? row.role : 'other',
            textLength: typeof row.text === 'string' ? row.text.length : null,
            identityFormat: typeof row.message_id !== 'string' ? 'absent' : /^[0-9a-f]{64}$/.test(row.message_id) ? 'sha256' : /^[0-9a-f-]{36}$/i.test(row.message_id) ? 'uuid' : 'other',
            identityLength: typeof row.message_id === 'string' ? row.message_id.length : null,
            timestampType: typeof row.created_at, timestampFinite: typeof row.created_at === 'number' && Number.isFinite(row.created_at),
          })),
          sourceCount: state.received.filter((event) => event.type === 'voice_compression_started' && event.callId === callId).at(-1)?.sourceMessageIds?.length ?? 0,
          coveredCount: compression?.coveredMessageIds?.length ?? 0 };
      } finally { database.close(); cryptoDatabase.close(); }
    }, STAGE_TWO_REPLY);
    await testInfo.attach('voice-history-diagnostic', { body: JSON.stringify(diagnostic), contentType: 'application/json' });
  } catch {
    await testInfo.attach('voice-history-diagnostic', { body: JSON.stringify({ captureFailed: true }), contentType: 'application/json' });
  }
});

async function observeRealTransport(page: Page, deferReady = false): Promise<void> {
  await page.addInitScript(({ expectedReply, deferReady }) => {
    let holdReady = deferReady;
    let audioBatch = 0;
    let nextAudioBatch = 0;
    const evidence = { sent: [], received: [], tracks: [] } as CallEvidence;
    // Browser-only shared decoder for the independent canonical durability fence
    // and failure diagnostics. No decrypted content or keys leave the browser.
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
    Object.assign(window, { __voiceCallEvidence: evidence });
    const NativeWebSocket = window.WebSocket;
    let nextSocketId = 0;
    window.WebSocket = new Proxy(NativeWebSocket, {
      construct(Target, args) {
        const socket: WebSocket = Reflect.construct(Target, args);
        const socketId = ++nextSocketId;
        const path = new URL(String(args[0]), window.location.href).pathname;
        if (path === '/v1/ws') {
          evidence.mainSocket = socket;
          evidence.mainSocketId = socketId;
        }
        const originalSend = socket.send.bind(socket);
        socket.send = (data) => {
          if (typeof data === 'string') {
            try {
              const event = JSON.parse(data);
              const payload = event.payload ?? event;
              if (event.type === 'mic_audio' && !audioBatch) {
                audioBatch = ++nextAudioBatch;
                queueMicrotask(() => { audioBatch = 0; });
              }
              if (['start', 'text_input', 'call_message_completed', 'encrypted_chat_metadata', 'store_chat_compression_checkpoint', 'chat_system_message_added', 'voice_compression_confirmed', 'voice_context_paused', 'chat_message_added', 'mic_audio', 'audio_stream_end', 'hangup', 'voice_memory_response', 'app_settings_memories_confirmed', 'voice_action_completed_confirmed'].includes(event.type)) {
                evidence.sent.push({
                  path, socketId, type: event.type, observedAt: performance.now(),
                  ...(event.type === 'mic_audio' ? { audioSamples: atob(payload.data).length / 2, audioBatch, audioNonzero: /[^\0]/.test(atob(payload.data)) } : {}),
                  messageId: payload.message_id ?? payload.message?.message_id ?? payload.assistant_message_id,
                  chatId: payload.chat_id, role: payload.role,
                  ...(['call_message_completed', 'encrypted_chat_metadata', 'chat_system_message_added'].includes(event.type) ? {
                    ciphertextLength: typeof (payload.message ?? payload).encrypted_content === 'string' ? (payload.message ?? payload).encrypted_content.length : 0,
                    plaintext: 'content' in (payload.message ?? payload) || 'text' in (payload.message ?? payload),
                    revision: payload.revision,
                  } : {}),
                  ...(event.type === 'start' ? { context: payload.context?.messages, summary: payload.context?.summary,
                    startupAllowanceMs: payload.startup_audio_allowance_ms } : {}),
                  ...(event.type === 'store_chat_compression_checkpoint' ? {
                    checkpointId: payload.checkpoint_id, coveredCount: payload.covered_message_ids?.length,
                    ciphertextLength: typeof payload.encrypted_summary === 'string' ? payload.encrypted_summary.length : 0,
                    plaintext: 'summary' in payload || 'summary_content' in payload,
                  } : {}),
                  ...(['voice_compression_confirmed', 'voice_context_paused'].includes(event.type) ? { checkpointId: payload.checkpoint_id } : {}),
                });
              }
            } catch { /* Observe without changing transport behavior. */ }
          }
          originalSend(data);
          if (path === '/v1/voice-call' && evidence.reconnectOnText && typeof data === 'string') {
            try {
              if (JSON.parse(data).type === 'text_input') {
                evidence.reconnectOnText = false;
                evidence.reconnectInjected = true;
                evidence.mainSocket?.close();
              }
            } catch { /* Preserve native transport if an unrelated frame arrives. */ }
          }
        };
        socket.addEventListener('message', (message) => {
          if (typeof message.data !== 'string') return;
          try {
            const event = JSON.parse(message.data);
            if (path === '/v1/voice-call' && event.type === 'ready' && holdReady) {
              // Delay delivery of the genuine ready bytes, preserving the real
              // authenticated socket/server. No microphone frame can pass yet.
              message.stopImmediatePropagation();
              evidence.readyHeld = true;
              evidence.releaseReady = () => {
                holdReady = false;
                evidence.readyHeld = false;
                socket.dispatchEvent(new MessageEvent('message', { data: message.data }));
              };
              return;
            }
            const payload = event.payload ?? event;
            if (['error', 'server_capabilities', 'usage', 'billing_activity', 'ready', 'transcript', 'call_message_confirmed', 'system_message_confirmed', 'call_message_rejected', 'chat_compression_checkpoint_stored', 'ended', 'voice_memory', 'voice_focus', 'voice_embed', 'voice_context', 'voice_compression_started', 'voice_compression', 'voice_context_pause', 'voice_context_resumed', 'voice_action_completed'].includes(event.type)) {
              evidence.received.push({ path, socketId, type: event.type, messageId: payload.message_id,
                ...(event.type === 'error' ? {
                  code: ['call_unavailable', 'context_too_large', 'transcript_limit'].includes(payload.code) ? payload.code : 'other',
                  stage: ['start_validation','context_options','personal_chat','session','credits','lock','registry','provider_selection','broker_creation','broker_prepare','prompt_configuration','provider_open','active'].includes(payload.stage) ? payload.stage : 'other',
                } : {}),
                chatId: payload.chat_id, role: payload.role, revision: payload.revision,
                assistantMessageId: event.assistant_message_id ?? payload.assistant_message_id,
                callId: event.call_id ?? payload.call_id, embedId: payload.embed_id ?? payload.embed_refs?.[0],
                ...(event.type === 'billing_activity' ? { inputListening: payload.input_listening, processing: payload.processing } : {}),
                ...(event.type === 'usage' ? {creditsCharged:payload.credits_charged} : {}),
                ...(event.type === 'transcript' ? { createdAt: payload.created_at, final: payload.final === true,
                  textLength: typeof payload.text === 'string' ? payload.text.length : 0,
                  expectedReply: typeof payload.text === 'string' && payload.text.includes(expectedReply) } : {}),
                ...(event.type === 'voice_compression_started' ? { snapshotId: payload.snapshot_id, sourceMessageIds: payload.message_ids } : {}) });
              if (['voice_compression', 'chat_compression_checkpoint_stored', 'voice_context_pause', 'voice_context_resumed'].includes(event.type)) {
                const observed = evidence.received.at(-1)!;
                observed.checkpointId = payload.summary_message_id ?? payload.checkpoint?.id ?? payload.checkpoint_id;
                observed.coveredCount = payload.covered_message_ids?.length ?? payload.checkpoint?.covered_message_ids?.length;
                if (event.type === 'voice_compression') {
                  observed.coveredMessageIds = payload.covered_message_ids;
                  observed.compressedMessageCount = payload.compressed_message_count;
                  observed.snapshotId = payload.voice_snapshot_id;
                  observed.boundaryTimestamp = payload.compressed_up_to_timestamp;
                }
              }
            }
            const target = evidence.hangupOnCommittedAction;
            const currentReady = evidence.received.filter(observed => observed.type === 'ready').at(-1);
            if (event.type === 'voice_action_completed' && target && payload.call_id === target.callId &&
                currentReady?.callId === target.callId && currentReady.socketId === target.socketId) {
              const hangup = document.querySelector<HTMLButtonElement>('[data-testid="voice-call-hangup"]');
              if (hangup) {
                evidence.hangupOnCommittedAction = undefined;
                evidence.committedHangupReceipt = evidence.received.at(-1);
                evidence.committedHangupInjected = true;
                hangup.click();
              }
            }
          } catch { /* Binary/provider audio is irrelevant to ciphertext proof. */ }
        });
        return socket;
      },
    });
    const originalCapture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await originalCapture(constraints);
      evidence.tracks.push(...stream.getTracks());
      return stream;
    };
  }, { expectedReply: STAGE_TWO_REPLY, deferReady });
}

async function evidence(page: Page): Promise<Omit<CallEvidence, 'tracks'>> {
  return page.evaluate(() => {
    const state = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence;
    return { sent: state.sent, received: state.received };
  });
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
      const local=await Promise.all(ids.map(id=>read<{encrypted_content?:string;content?:string;role:string;chat_id:string;created_at:number}|undefined>(db,'messages',id)));
      if(local.some(row=>!row?.encrypted_content||typeof row.content==='string'||row.chat_id!==chatId)) return {durable:0,decryptedEvents:0,privateRows:false,pair:false,times:false,duration:false};
      const remote=new Map<string,{message_id:string;encrypted_content:string;role:string;created_at:number}>();
      const params=new URLSearchParams({direction:'latest',limit:'20',respect_compression_boundary:'false'});
      for(let window=0;window<8;window++) {
        const response=await fetch(`${apiUrl}/v1/chats/${encodeURIComponent(chatId)}/messages/window?${params}`,{credentials:'include'});
        if(!response.ok) return {durable:0,decryptedEvents:0,privateRows:true,pair:false,times:false,duration:false};
        const history=await response.json();
        for(const row of history.messages??[]) remote.set(row.message_id,row);
        if(!history.has_more_before||!history.start_cursor) break;
        params.set('direction','before');params.set('before_timestamp',String(history.start_cursor.created_at));params.set('before_message_id',history.start_cursor.message_id);
      }
      const durable=ids.filter((id,index)=>remote.get(id)?.encrypted_content===local[index]?.encrypted_content).length;
      const master=await read<CryptoKey>(keys,'keys','master_key');
      const chat=await read<{encrypted_chat_key:string}>(db,'chats',chatId);
      const bytes=(value:string)=>Uint8Array.from(atob(value),char=>char.charCodeAt(0));
      const wrapped=bytes(chat.encrypted_chat_key);
      const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv:wrapped.slice(0,12)},master,wrapped.slice(12));
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
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

async function assertHeaderCallActions(page: Page, active: boolean, hasClose: boolean): Promise<void> {
  const call = page.locator('[data-testid="voice-call-start"]:visible');
  if (active) {
    await expect(call).toHaveCount(0);
    const bar=page.getByTestId('voice-call-bar');
    await expect(bar).toBeVisible();
    await expect(page.getByTestId('voice-call-hangup')).toHaveAccessibleName('Hang up');
    await expect(page.getByTestId('voice-call-video')).toHaveAccessibleName('Video call');
    const [video,center,end]=await Promise.all(['voice-call-video','voice-call-mute','voice-call-hangup'].map(id=>page.getByTestId(id).boundingBox()));
    expect(video!.x+video!.width).toBeLessThanOrEqual(center!.x+1);
    expect(center!.x+center!.width).toBeLessThanOrEqual(end!.x+1);
    if(hasClose) await expect(page.locator('[data-testid="chat-close-button"]:visible,[data-testid="voice-call-close-chat"]:visible')).toHaveCount(1);
    await assertSlimCallSurface(page);
    return;
  }
  await expect(call).toHaveCount(1);
  await expect(call).toHaveAccessibleName('Start voice call');
  await expect(call).toHaveAccessibleDescription('Voice calls use Google Gemini with usage-based billing.');
  await expect(call).toHaveAttribute('aria-pressed','false');
  const handset=call.getByTestId('voice-call-handset');
  await expect(handset).toHaveAttribute('data-icon','audiocall');
  await expect(handset).not.toHaveCSS('mask-image','none');
  await expect(handset).toHaveCSS('transform','matrix(1, 0, 0, 1, 0, 0)');
  const close=page.locator('[data-testid="chat-close-button"]:visible');
  await expect(close).toHaveCount(hasClose?1:0);
  if(hasClose) {
    const [left,right]=await Promise.all([call.boundingBox(),close.boundingBox()]);
    expect(right!.x).toBeGreaterThanOrEqual(left!.x+left!.width);
    expect(Math.abs(left!.y+left!.height/2-right!.y-right!.height/2)).toBeLessThan(1);
  }
}

/** Completed skill activity uses the same disclosure as ordinary text replies. */
async function expandWebActivity(page: Page, assistant: Locator): Promise<void> {
  const dismissInput = page.getByTestId('input-dismiss-button');
  if (await dismissInput.isVisible()) await dismissInput.click();
  const groups = assistant.getByTestId('assistant-activity-group').filter({
    has: page.locator('[data-testid="assistant-activity-icons"] [data-app-id="web"]'),
  });
  await expect.poll(() => groups.count()).toBeGreaterThan(0);
  for (const group of await groups.all()) {
    const toggle = group.getByTestId('assistant-activity-toggle');
    await toggle.scrollIntoViewIfNeeded();
    await expect(toggle).toHaveAttribute('aria-expanded', /^(true|false)$/);
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(group.getByTestId('assistant-activity-body')).toBeVisible();
  }
}

/** Reloaded compressed chats expose their original rows through native history. */
async function showForgottenHistory(page: Page): Promise<void> {
  const dismissInput = page.getByTestId('input-dismiss-button');
  if (await dismissInput.isVisible()) await dismissInput.click();
  const toggle = page.getByTestId('show-forgotten-messages');
  await expect(toggle).toBeVisible({ timeout: 45_000 });
  await toggle.scrollIntoViewIfNeeded();
  await expect(toggle).toContainText('Show old forgotten messages');
  await toggle.click();
  await expect(toggle).toContainText('Hide old forgotten messages', { timeout: 45_000 });
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
async function seedVoiceContext(page: Page, chatId: string, coveredIds: string[], uncoveredCount = 25): Promise<string[]> {
  const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL;
  expect(apiUrl, 'isolated CI must supply its private API URL').toBeTruthy();
  // Reloaded history renders locally before the asynchronous main connection.
  // server_capabilities is issued after authentication/connection registration;
  // bind readiness to the current socket, including after a native reconnect.
  await expect.poll(() => page.evaluate(() => {
    const state = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence;
    return {
      path: state.mainSocket ? new URL(state.mainSocket.url).pathname : null,
      readyState: state.mainSocket?.readyState ?? -1,
      authenticated: state.received.some((event) => event.type === 'server_capabilities' && event.socketId === state.mainSocketId),
    };
  }), { timeout: 30_000, message: 'Existing main transport must be open and authenticated before encrypted history seeding' })
    .toEqual({ path: '/v1/ws', readyState: 1, authenticated: true });
  const uncovered = await page.evaluate(async ({ chatId, coveredIds, fact, oldestUncoveredFact, uncoveredCount }) => {
    const open = (name: string) => new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(name);
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    const read = <T>(db: IDBDatabase, store: string, id: string) => new Promise<T>((resolve, reject) => {
      const request = db.transaction(store, 'readonly').objectStore(store).get(id);
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    const database = await open('chats_db');
    const cryptoDatabase = await open('openmates_crypto');
    try {
      const masterKey = await read<CryptoKey>(cryptoDatabase, 'keys', 'master_key');
      if (!masterKey) throw new Error('Fixture requires an authenticated browser master key');
      const chat = await read<{ encrypted_chat_key: string; messages_v: number }>(database, 'chats', chatId);
      const wrapped = Uint8Array.from(atob(chat.encrypted_chat_key), (char) => char.charCodeAt(0));
      const rawKey = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: wrapped.slice(0, 12) }, masterKey, wrapped.slice(12));
      const chatKey = await crypto.subtle.importKey('raw', rawKey, 'AES-GCM', false, ['encrypt']);
      const encrypt = async (text: string, key: CryptoKey) => {
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(text)));
        const bytes = new Uint8Array(iv.length + ciphertext.length); bytes.set(iv); bytes.set(ciphertext, iv.length);
        return btoa(String.fromCharCode(...bytes));
      };
      const covered = await Promise.all(coveredIds.map((id) => read<{ message_id: string; created_at: number }>(database, 'messages', id)));
      const boundary = covered.sort((a, b) => a.created_at - b.created_at || a.message_id.localeCompare(b.message_id)).at(-1)!;
      // Longer than the old 2,000-character overview slice, with the key fact at
      // the end: the test fails if call admission discards checkpoint meaning.
      const summary = 'Earlier turns established broth, noodles and timing. '.repeat(70) + fact;
      const encryptedSummary = await encrypt(summary, chatKey);
      const encryptedMemory = await encrypt(JSON.stringify({ title: 'Voice fixture preference', technologies: ['TypeScript'], notes: 'Fictional selected private memory' }), masterKey);
      // The default twenty-five rows force a second native window read; the
      // final refusal case uses thirty-one to exceed gateway admission safely.
      // Fresh globally unique IDs prevent cross-account/retry ownership collisions;
      // sorted UUID ordering puts the unique fact outside the latest24 window.
      // Keep fictional history after the approved checkpoint. The bounded clock
      // fence below ensures it predates the next call's protected audio cohort.
      const uncoveredAt = Math.max(boundary.created_at + 1, Math.floor(Date.now() / 1000) - 1);
      const uncoveredIds = Array.from({ length: uncoveredCount }, () => crypto.randomUUID()).sort();
      const encryptedSender = await encrypt('You', chatKey);
      const encryptedCategory = await encrypt('general_knowledge', chatKey);
      const uncovered = await Promise.all(uncoveredIds.map(async (messageId, index) => ({
        message_id: messageId, chat_id: chatId,
        role: 'user', status: 'synced', created_at: uncoveredAt,
        encrypted_sender_name: encryptedSender, encrypted_category: encryptedCategory,
        encrypted_content: await encrypt(index === 0 ? oldestUncoveredFact : `Fictional uncovered recipe detail ${index}.`, chatKey),
      })));
      await new Promise<void>((resolve, reject) => {
        const tx = database.transaction(['chat_compression_checkpoints', 'app_settings_memories'], 'readwrite');
        tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
        tx.objectStore('chat_compression_checkpoints').put({ id: crypto.randomUUID(), chat_id: chatId,
          encrypted_summary: encryptedSummary, compressed_up_to_timestamp: boundary.created_at,
          compressed_up_to_message_id: boundary.message_id, covered_message_ids: coveredIds,
          compressed_message_count: coveredIds.length, summary_token_estimate: 1000, created_at: Math.floor(Date.now() / 1000) });
        tx.objectStore('app_settings_memories').put({ id: crypto.randomUUID(), app_id: 'code',
          item_type: 'preferred_tech', item_key: 'voice-fixture-private-entry', encrypted_item_json: encryptedMemory,
          encrypted_app_key: '', item_version: 1, created_at: Math.floor(Date.now() / 1000), updated_at: Math.floor(Date.now() / 1000) });
      });
      const socket = (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence.mainSocket;
      if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error('Encrypted fixture requires the authenticated main socket');
      // Existing storage-only operation checks the canonical owner and wrapped
      // chat key, and queues ciphertext persistence without an AI request.
      for (const [index, row] of uncovered.entries()) socket.send(JSON.stringify({
        type: 'encrypted_chat_metadata', payload: {
          chat_id: chatId, message_id: row.message_id, encrypted_content: row.encrypted_content,
          encrypted_sender_name: row.encrypted_sender_name, encrypted_category: row.encrypted_category,
          encrypted_chat_key: chat.encrypted_chat_key, created_at: row.created_at,
          versions: { messages_v: (chat.messages_v ?? 0) + index + 1, last_edited_overall_timestamp: uncoveredAt },
        },
      }));
      return uncovered;
    } finally { database.close(); cryptoDatabase.close(); }
  }, { chatId, coveredIds, fact: CHECKPOINT_FACT, oldestUncoveredFact: UNCOVERED_CONTEXT_FACT, uncoveredCount });

  // A chat_message_confirmed receipt only means its message task was queued.
  // The authenticated canonical reader is the durability fence for compression.
  // Keep ciphertext comparisons in memory; failures report only a matched count.
  await expect.poll(async () => {
    const params = new URLSearchParams({ direction: 'latest', limit: '20', respect_compression_boundary: 'false' });
    const stored = new Map<string, string>();
    let matched = 0;
    // The reader caps each window at20, so follow its native cursor rather than
    // treating a larger requested limit as a complete durability observation.
    for (let window = 0; window < 3; window += 1) {
      const response = await page.request.get(`${apiUrl}/v1/chats/${encodeURIComponent(chatId)}/messages/window?${params}`);
      expect(response.ok(), 'Authenticated encrypted history reader must accept the owned chat').toBe(true);
      const history = await response.json();
      for (const row of history.messages ?? []) stored.set(row.message_id, row.encrypted_content);
      matched = uncovered.filter((row) => stored.get(row.message_id) === row.encrypted_content).length;
      if (matched === uncovered.length || !history.has_more_before || !history.start_cursor) break;
      params.set('direction', 'before');
      params.set('before_timestamp', String(history.start_cursor.created_at));
      params.set('before_message_id', history.start_cursor.message_id);
    }
    return matched;
  }, { timeout: 45_000, intervals: [250, 500, 1000], message: 'All fictional encrypted history rows must be durable before voice compression' }).toBe(uncoveredCount);

  await page.evaluate(async (rows) => {
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('chats_db');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    try {
      await new Promise<void>((resolve, reject) => {
        const tx = database.transaction('messages', 'readwrite');
        tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
        for (const row of rows) tx.objectStore('messages').put(row);
      });
    } finally { database.close(); }
  }, uncovered);
  await expect.poll(() => page.evaluate(() => Math.floor(Date.now() / 1000)), {
    timeout: 5_000, intervals: [100],
    message: 'Fictional prior history must precede the next voice turn by an integer timestamp second',
  }).toBeGreaterThan(uncovered[0].created_at);
  return uncovered.map((row) => row.message_id);
}

test.describe('Integrated voice-call foundation', () => {
  // contract-test: direct surface=gui.web assertions=video-call.privacy,video-call.usage.provider-metering,video-call.chat.call-events
  test('refuses an unauthenticated call before opening a provider session', async ({ page }) => {
    const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL;
    expect(apiUrl, 'isolated CI must supply its private API URL').toBeTruthy();
    await observeRealTransport(page);
    await page.goto('/');
    const result = await page.evaluate((url) => new Promise<{ ready: boolean; closed: boolean }>((resolve) => {
      const socket = new WebSocket(`${url.replace(/^http/, 'ws')}/v1/voice-call`);
      let ready = false;
      const timeout = setTimeout(() => { socket.close(); resolve({ ready, closed: false }); }, 10_000);
      socket.addEventListener('message', (event) => {
        try { ready ||= JSON.parse(event.data).type === 'ready'; } catch { /* A refusal has no provider content. */ }
      });
      socket.addEventListener('close', () => { clearTimeout(timeout); resolve({ ready, closed: true }); });
    }), apiUrl!);
    expect(result).toEqual({ ready: false, closed: true });
    expect((await evidence(page)).sent.filter(event=>event.type==='chat_system_message_added')).toHaveLength(0);
    await expect(page.getByTestId('voice-call-started')).toHaveCount(0);
    await expect(page.getByTestId('voice-call-ended')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.transcripts,video-call.chat.typed-input,video-call.chat.call-events,video-call.lifecycle.recovery-and-billing
  test('uses the latest committed call version when ordinary text resumes after hangup', async ({ page }, testInfo) => {
    test.setTimeout(180_000);
    expect(process.env.E2E_USE_MOCKS,'Ordinary turns must use the existing deterministic replay fixture').toBeTruthy();
    expect(process.env.E2E_RECORD_FIXTURES).toBeFalsy();
    expect(process.env.GITHUB_ACTIONS).toBe('true');
    expect(process.env.RUNNER_ENVIRONMENT).toBe('github-hosted');
    expect(process.env.CI_TEST_MODE).toBe('e2e');
    type VersionFrame = {direction:'sent'|'received';type:string;chatId?:string;messageId?:string;turnId?:string;jobId?:string;
      version?:number;expectedVersion?:number;state?:string;rejected:boolean;rejectionCode?:string};
    const protocol:VersionFrame[]=[];
    const serverStatuses:Array<{ok:boolean;isSelfHosted:boolean|null;isDevelopment:boolean|null;modelsConfiguredBefore:boolean|null;modelsConfiguredAfter:boolean}>=[];
    const sendCheckpoints:string[]=[];
    const sendSnapshots:unknown[]=[];
    let phase='setup';
    let proofComplete=false;
    const checkpoint=(message:string)=>{
      const kind=/did not persist/i.test(message)?'send_not_persisted':/failed|error/i.test(message)?'send_error':/dispatch/i.test(message)?'send_dispatch':/send button/i.test(message)?'send_button':'send_checkpoint';
      sendCheckpoints.push(`${phase}:${kind}`);if(sendCheckpoints.length>16)sendCheckpoints.shift();
    };
    const retainSendDebug=async()=>{
      const snapshot=await page.evaluate(async()=>{
        const browser=window as unknown as {__openmatesLastSendDebug?:{step?:unknown;details?:Record<string,unknown>};
          __openmatesLastPreflightDebug?:{step?:unknown};__openmatesE2EChatConnectionState?:()=>Promise<Record<string,unknown>>};
        const send=browser.__openmatesLastSendDebug;
        const details=send?.details??{};
        const error=details.error as {name?:unknown;message?:unknown;stack?:unknown}|undefined;
        // Keep only fixed-format step labels, error classes/categories and booleans.
        // Raw error messages, debug details, editor text and transport bodies stay local.
        const step=(value:unknown)=>typeof value==='string'&&/^[a-z][a-z0-9_]{0,79}$/.test(value)?value:null;
        const errorName=typeof error?.name==='string'&&['Error','TypeError','ReferenceError','AbortError','InvalidStateError','NotAllowedError','OperationError','TimeoutError','DataError','NotFoundError','QuotaExceededError'].includes(error.name)?error.name:null;
        const message=typeof error?.message==='string'?error.message:'';
        const errorCategory=!error?null:/self.hosted|models.*config|no.*models/i.test(message)?'models_unconfigured':/credit|balance/i.test(message)?'credits':/encrypt|crypt|key/i.test(message)?'crypto':/preflight|version|recovery|admission/i.test(message)?'admission':/auth|token|session/i.test(message)?'auth':/network|websocket|offline/i.test(message)?'transport':'other';
        // Retain only source-location stack frames; omit the error headline and arbitrary text.
        const errorStackFrames=typeof error?.stack==='string'?error.stack.split('\n').slice(1).map(frame=>frame.trim())
          .filter(frame=>/^at (?:[\w.$<>]+ \()?https?:\/\/[^/\s]+\/(?:_app\/immutable\/|node_modules\/|src\/)[\w./@-]+:\d+:\d+\)?$/.test(frame)).slice(0,6):[];
        const connection=await browser.__openmatesE2EChatConnectionState?.().catch(()=>null);
        return {sendStep:step(send?.step),failedAfterStep:step(details.failedAfterStep),preflightStep:step(browser.__openmatesLastPreflightDebug?.step),
          errorName,errorCategory,...(errorStackFrames.length?{errorStackFrames}:{}),hasMessagePayload:details.hasMessagePayload===true,
          editorHasText:!!document.querySelector('[data-testid="message-editor"] [contenteditable="true"]')?.textContent?.trim(),
          online:connection?.online===true,websocketConnected:connection?.websocketConnected===true,cachePrimed:connection?.cachePrimed===true,
          contextSyncCompleted:connection?.contextSyncCompleted===true,teamContextActive:connection?.teamContextActive===true};
      }).catch(()=>({captureFailed:true}));
      sendSnapshots.push({phase,snapshot});if(sendSnapshots.length>4)sendSnapshots.shift();
    };
    const kinds=new Set(['chat_turn_admit','chat_turn_preflight','chat_message_added','chat_message_confirmed',
      'ai_response_completed','ai_response_storage_confirmed','call_message_confirmed','call_message_changed','system_message_confirmed']);
    page.on('websocket',socket=>{
      if(new URL(socket.url()).pathname!=='/v1/ws')return;
      const observe=(direction:VersionFrame['direction'])=>(frame:{payload:string|Buffer})=>{
        try{
          const message=JSON.parse(String(frame.payload));
          if(typeof message.type!=='string')return;
          const p=message.payload??message;
          const rejected=/rejected|error$/.test(message.type)||p.accepted===false||p.status==='rejected'||
            [p.code,p.error_code,p.error].some(value=>typeof value==='string'&&/version|stale|conflict/i.test(value));
          if(!kinds.has(message.type)&&!rejected)return;
          const rejectionCode=p.code??p.error_code??p.error;
          // Only authentic canonical fields are observed: never queue revision,
          // optimistic row counts, plaintext, encrypted payloads or recovery keys.
          const version=['call_message_confirmed','call_message_changed','system_message_confirmed'].includes(message.type)
            ? p.messages_v : p.committed_messages_v??p.new_messages_v??p.versions?.messages_v??p.messages_v;
          protocol.push({direction,type:message.type,chatId:p.chat_id??p.encrypted_assistant_message?.chat_id,
            messageId:p.message_id??p.encrypted_user_message?.client_message_id??p.encrypted_assistant_message?.client_message_id??p.message?.message_id,
            turnId:p.turn_id,jobId:p.job_id,version:typeof version==='number'?version:undefined,
            expectedVersion:typeof p.expected_messages_v==='number'?p.expected_messages_v:undefined,
            state:p.state==='TERMINAL'?'TERMINAL':undefined,rejected,
            rejectionCode:rejected&&typeof rejectionCode==='string'&&/^[a-z_]{1,64}$/i.test(rejectionCode)?rejectionCode:undefined});
        }catch{/* Ignore transport control frames; retain no raw payload. */}
      };
      socket.on('framesent',observe('sent'));socket.on('framereceived',observe('received'));
    });
    try{
    // Match the established isolated first-chat fixture: fetch the real status
    // and open only its UI availability gate, without adding provider credentials.
    await page.route('**/v1/settings/server-status',async route=>{
      const response=await route.fetch();
      if(!response.ok()){
        serverStatuses.push({ok:false,isSelfHosted:null,isDevelopment:null,modelsConfiguredBefore:null,modelsConfiguredAfter:false});
        if(serverStatuses.length>4)serverStatuses.shift();
        throw new Error(`Server status failed (${response.status()}).`);
      }
      const status=await response.json();
      serverStatuses.push({ok:true,isSelfHosted:typeof status.is_self_hosted==='boolean'?status.is_self_hosted:null,
        isDevelopment:typeof status.is_development==='boolean'?status.is_development:null,
        modelsConfiguredBefore:typeof status.ai_models_configured==='boolean'?status.ai_models_configured:null,modelsConfiguredAfter:true});
      if(serverStatuses.length>4)serverStatuses.shift();
      await route.fulfill({response,json:{...status,ai_models_configured:true}});
    });
    await installNativeVoiceInput(page);
    await observeRealTransport(page);
    await loginToTestAccount(page);
    await waitForChatReady(page);
    await startNewChat(page);
    await waitForChatReady(page);
    await expect(page.getByTestId('message-user')).toHaveCount(0);
    const ordinaryText='Capital of Germany?';
    const testMockMarker=withMockMarker(ordinaryText,'chat_flow_capital','instant');
    expect(testMockMarker).toBeTruthy();
    phase='ordinary_seed';
    await sendMessage(page,withMockMarker(ordinaryText,'chat_flow_capital','instant'),checkpoint,retainSendDebug,'ordinary-seed');
    await waitForAssistantMessage(page,{which:'last',contains:'The capital of Germany is Berlin.'});
    await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
    const chatId=new URL(page.url()).hash.match(/chat-id=([^&]+)/)?.[1];
    expect(chatId).toBeTruthy();
    const admissions=(frames:VersionFrame[])=>frames.filter(frame=>frame.direction==='sent'&&frame.chatId===chatId&&['chat_turn_admit','chat_turn_preflight'].includes(frame.type));
    expect(admissions(protocol)).toHaveLength(1);
    const seedAdmission=admissions(protocol)[0];
    expect(seedAdmission.messageId).toBeTruthy();expect(seedAdmission.turnId).toBeTruthy();
    const seedAssistantId=await page.getByTestId('message-assistant').filter({hasText:'The capital of Germany is Berlin.'}).last().getAttribute('data-message-id');
    expect(seedAssistantId).toBeTruthy();
    // Epoch-zero admissions use legacy assistant persistence. Its storage ACK has no version.
    await expect.poll(()=>protocol.some(frame=>frame.direction==='sent'&&frame.type==='ai_response_completed'&&frame.chatId===chatId&&frame.messageId===seedAssistantId),{timeout:45_000}).toBe(true);
    await expect.poll(()=>protocol.some(frame=>frame.direction==='received'&&frame.type==='ai_response_storage_confirmed'&&frame.chatId===chatId&&frame.messageId===seedAssistantId),{timeout:45_000}).toBe(true);
    const apiUrl=process.env.PLAYWRIGHT_TEST_API_URL;expect(apiUrl).toBeTruthy();
    const canonical=(ids:string[],requireEncrypted=false)=>page.evaluate(async({apiUrl,chatId,ids,requireEncrypted})=>{
      const response=await fetch(`${apiUrl}/v1/chats/${encodeURIComponent(chatId)}/messages/window?direction=latest&limit=20&respect_compression_boundary=false`,{credentials:'include'});
      const window=await response.json();
      return {ok:response.ok,version:window.messages_v,counts:ids.map(id=>(window.messages??[]).filter((row:{message_id:string;encrypted_content?:unknown})=>row.message_id===id&&(!requireEncrypted||(typeof row.encrypted_content==='string'&&row.encrypted_content.length>0))).length)};
    },{apiUrl:apiUrl!,chatId:chatId!,ids,requireEncrypted});
    await expect.poll(async()=>{const stored=await canonical([seedAdmission.messageId!,seedAssistantId!],true);return stored.ok&&Number.isSafeInteger(stored.version)&&stored.version>0&&stored.counts.every(count=>count===1);},{timeout:45_000}).toBe(true);
    const seedVersion=(await canonical([seedAdmission.messageId!,seedAssistantId!],true)).version;
    expect(Number.isSafeInteger(seedVersion)).toBe(true);expect(seedVersion).toBeGreaterThan(0);
    const localSynced=(assistantId:string,version:number)=>page.evaluate(async({chatId,assistantId,version})=>{
      const db=await new Promise<IDBDatabase>((resolve,reject)=>{const open=indexedDB.open('chats_db');open.onsuccess=()=>resolve(open.result);open.onerror=()=>reject(open.error);});
      const read=(store:string,id:string)=>new Promise<Record<string,unknown>|undefined>((resolve,reject)=>{const request=db.transaction(store,'readonly').objectStore(store).get(id);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
      try{const [chat,assistant]=await Promise.all([read('chats',chatId),read('messages',assistantId)]);return chat?.messages_v===version&&assistant?.status==='synced';}
      finally{db.close();}
    },{chatId:chatId!,assistantId,version});
    await expect.poll(()=>localSynced(seedAssistantId!,seedVersion),{timeout:45_000}).toBe(true);

    phase='voice_call';
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now',{timeout:45_000});
    await expect(page.getByTestId('message-user').filter({hasText:USER_SPEECH})).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({hasText:ASSISTANT_SPEECH})).toHaveCount(1);
    expect(voiceFrames(await evidence(page),'start')[0].chatId).toBe(chatId);
    await expect.poll(async()=>voiceFrames(await evidence(page),'mic_audio').length).toBeGreaterThan(0);
    await page.getByTestId('voice-call-mute').click();
    const editor=page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await editor.click();await page.keyboard.insertText(PASTED_TEXT);await page.getByTestId('composer-send-button').click();
    await expect(page.getByTestId('message-user').filter({hasText:PASTED_TEXT})).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({hasText:'I received your text: '+PASTED_TEXT})).toHaveCount(1);
    await expect.poll(()=>new Set(protocol.filter(frame=>frame.direction==='received'&&frame.type==='call_message_confirmed'&&frame.chatId===chatId&&Number.isSafeInteger(frame.version)).map(frame=>frame.messageId)).size,{timeout:45_000}).toBe(4);
    const callReceipts=protocol.filter(frame=>frame.direction==='received'&&frame.type==='call_message_confirmed'&&frame.chatId===chatId);
    expect(callReceipts.every(frame=>Number.isSafeInteger(frame.version)&&frame.version!>seedVersion)).toBe(true);
    const callTranscriptIds=[...new Set(callReceipts.map(frame=>frame.messageId).filter((id):id is string=>!!id))];
    expect(callTranscriptIds).toHaveLength(4);
    const callReady=(await evidence(page)).received.find(frame=>frame.type==='ready'&&frame.path==='/v1/voice-call');
    expect(callReady?.callId).toBeTruthy();
    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await assertVoiceInputCleanup(page);
    await assertCallHistoryDurable(page,chatId!,callReady!.callId!,callTranscriptIds);
    const endedId=`ffffffff-voice-call-${callReady!.callId}-ended`;
    await expect.poll(()=>protocol.some(frame=>frame.direction==='received'&&frame.type==='system_message_confirmed'&&frame.messageId===endedId&&Number.isSafeInteger(frame.version)),{timeout:45_000}).toBe(true);
    const endVersion=protocol.find(frame=>frame.direction==='received'&&frame.type==='system_message_confirmed'&&frame.messageId===endedId)!.version!;
    expect(endVersion).toBeGreaterThan(seedVersion);
    expect(endVersion).toBeGreaterThanOrEqual(Math.max(...callReceipts.map(frame=>frame.version!)));
    await expect.poll(()=>canonical([endedId,...callTranscriptIds]),{timeout:45_000}).toEqual({ok:true,version:endVersion,counts:[1,1,1,1,1]});

    // No reload, cache reset or barrier manipulation: exercise the normal sender
    // after the legacy durable ACK and the call's authenticated receipts.
    const postCallStart=protocol.length;
    phase='ordinary_post_call';
    await sendMessage(page,withMockMarker(ordinaryText,'chat_flow_capital','instant'),checkpoint,retainSendDebug,'ordinary-post-call');
    await waitForAssistantMessage(page,{which:'last',contains:'The capital of Germany is Berlin.'});
    await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
    const postCall=protocol.slice(postCallStart);
    expect(admissions(postCall)).toHaveLength(1);
    const resumed=admissions(postCall)[0];
    expect(resumed.chatId).toBe(chatId);expect(resumed.messageId).toBeTruthy();
    expect(resumed.messageId).not.toBe(seedAdmission.messageId);
    expect(resumed.expectedVersion).toBe(endVersion);
    expect(postCall.filter(frame=>frame.direction==='received'&&frame.rejected)).toHaveLength(0);
    expect(postCall.filter(frame=>frame.direction==='received'&&frame.type==='chat_message_confirmed'&&frame.messageId===resumed.messageId&&frame.version===endVersion+1)).toHaveLength(1);
    await expect(page.getByTestId('message-user').filter({hasText:'Capital of Germany?'})).toHaveCount(2);
    await expect(page.getByTestId('message-assistant').filter({hasText:'The capital of Germany is Berlin.'})).toHaveCount(2);
    const resumedAssistantId=await page.getByTestId('message-assistant').filter({hasText:'The capital of Germany is Berlin.'}).last().getAttribute('data-message-id');
    expect(resumedAssistantId).toBeTruthy();expect(resumedAssistantId).not.toBe(seedAssistantId);
    await expect.poll(()=>protocol.slice(postCallStart).some(frame=>frame.direction==='sent'&&frame.type==='ai_response_completed'&&frame.chatId===chatId&&frame.messageId===resumedAssistantId),{timeout:45_000}).toBe(true);
    await expect.poll(()=>protocol.slice(postCallStart).some(frame=>frame.direction==='received'&&frame.type==='ai_response_storage_confirmed'&&frame.chatId===chatId&&frame.messageId===resumedAssistantId),{timeout:45_000}).toBe(true);
    await expect.poll(async()=>{const stored=await canonical([resumed.messageId!,resumedAssistantId!],true);return stored.ok&&Number.isSafeInteger(stored.version)&&stored.version>endVersion&&stored.counts.every(count=>count===1);},{timeout:45_000}).toBe(true);
    const finalVersion=(await canonical([resumed.messageId!,resumedAssistantId!],true)).version;
    expect(Number.isSafeInteger(finalVersion)).toBe(true);expect(finalVersion).toBeGreaterThan(endVersion);
    expect((await canonical([resumed.messageId!,resumedAssistantId!],true)).counts).toEqual([1,1]);
    await expect.poll(()=>localSynced(resumedAssistantId!,finalVersion),{timeout:45_000}).toBe(true);
    await testInfo.attach('voice-call-canonical-version-proof',{body:JSON.stringify({ordinarySeedDurable:true,callTranscriptRows:callTranscriptIds.length,
      callReceiptsAdvanced:true,endReceiptMatchesCanonical:true,postCallAdmissions:1,postCallExpectedMatchesCanonical:true,
      postCallUserAcceptedOnce:true,staleVersionRejections:0,deterministicAssistantCompletions:2}),contentType:'application/json'});
    proofComplete=true;
    }finally{
      if(!proofComplete){
        await retainSendDebug();
        const frames=protocol.slice(-40).map(frame=>({direction:frame.direction,type:kinds.has(frame.type)?frame.type:'other_rejected_event',
          version:frame.version,expectedVersion:frame.expectedVersion,state:frame.state,rejected:frame.rejected,rejectionCode:frame.rejectionCode}));
        await testInfo.attach('voice-call-version-send-failure',{body:JSON.stringify({phase,serverStatuses,sendCheckpoints,sendSnapshots,
          totalProtocolFrames:protocol.length,protocol:frames}),contentType:'application/json'});
      }
    }
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning,video-call.audio.single-owner
  test('requires a saved Google processing acknowledgement before first capture and remembers it after reload', async ({ page }, testInfo) => {
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
        const acknowledgement=url.pathname==='/v1/settings/voice-google-processing-ack';
        if(acknowledgement)events.push(method==='POST'?'ack_post':'ack_get');
        const response=await nativeFetch(input,init);
        if(acknowledgement){
          if(method==='POST'){
            const json=response.json.bind(response);
            response.json=async()=>{
              const payload=await json();
              if(response.ok&&payload.version===1&&payload.acknowledged===true&&Number.isSafeInteger(payload.acknowledged_at)&&payload.acknowledged_at>0)events.push('ack_saved');
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
        const response=await fetch(`${apiUrl}/v1/settings/voice-google-processing-ack/fixture`,{
          method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({action}),
        });
        return {status:response.status,configured:(await response.json()).configured===true};
      },{apiUrl:apiUrl!,action});
      expect(configured).toEqual({status:200,configured:true});
    };
    const profileAcknowledgement=()=>page.evaluate(async apiUrl=>{
      const response=await fetch(`${apiUrl}/v1/settings/voice-google-processing-ack`,{credentials:'include'});
      const profile=await response.json();
      return {ok:response.ok,versionValid:profile.version===1,acknowledged:profile.acknowledged===true,
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
    await expect(notice).toContainText('Google processes your voice and the conversation context shared with this call. Google states that data sent through its paid Gemini API is not used to train its models.');
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
    await expect(page.getByTestId('message-user').filter({hasText:USER_SPEECH})).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({hasText:ASSISTANT_SPEECH})).toHaveCount(1);
    await expect.poll(async()=>new Set((await evidence(page)).sent.filter(event=>event.type==='call_message_completed').map(event=>event.messageId).filter((id):id is string=>!!id)).size).toBe(2);
    const firstTranscriptIds=[...new Set((await evidence(page)).sent.filter(event=>event.type==='call_message_completed').map(event=>event.messageId).filter((id):id is string=>!!id))];
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

  // contract-test: direct surface=gui.web assertions=video-call.audio.background-detection,video-call.audio.automatic-idle,video-call.audio.single-owner,video-call.chat.activity-status,video-call.usage.provider-metering,video-call.lifecycle.recovery-and-billing,video-call.audio.confirmation-sounds
  test('keeps a cold call billable, idles on verified silence and resumes buffered short speech on the same socket', async ({ page, context }) => {
    test.setTimeout(150_000);
    await installNativeVoiceInput(page);
    await observeRealTransport(page);
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    let modelRequested = false;
    let releaseModel!: () => void;
    const heldModel = new Promise<void>((resolve) => { releaseModel = resolve; });
    await context.route('**/*silero_vad_v5*', async (route) => {
      if (route.request().resourceType() === 'script') { await route.continue(); return; }
      modelRequested = true;
      await heldModel;
      await route.continue();
    });
    expect(modelRequested).toBe(false);
    try {
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      const status = page.getByTestId('voice-call-status-text');
      await assertSlimCallSurface(page);
      await expect.poll(() => modelRequested, { timeout: 20_000 }).toBe(true);
      await expect(status).toHaveText('Listening · You can speak now');
      await expect.poll(async () => (await nativeVoiceInput(page)).localToneStarts).toBeGreaterThan(0);
      const connectedTones = (await nativeVoiceInput(page)).localToneStarts;
      await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH }).getByTestId('generated-by')).toContainText(/Gemini.*Live/i);
      const started = await evidence(page);
      const start = voiceFrames(started, 'start')[0];
      expect(start.startupAllowanceMs).toBe(10_000);
      expect(started.received.filter((frame) => frame.type === 'ready' && frame.path === '/v1/voice-call')).toHaveLength(1);
      const coldCount = voiceFrames(started, 'mic_audio').length;
      await expect.poll(async () => voiceFrames(await evidence(page), 'mic_audio').length).toBeGreaterThan(coldCount + 12);
      const inputSeconds=await activeCallSeconds(page);
      await expect.poll(()=>activeCallSeconds(page)).toBeGreaterThan(inputSeconds);
      await expect.poll(async () => (await evidence(page)).received.filter((frame) => frame.type === 'billing_activity').at(-1))
        .toMatchObject({ inputListening: true, processing: false });
      await assertActivityCounter(page,true);
      await expect.poll(async()=>(await evidence(page)).received.some(frame=>frame.type==='usage'&&typeof frame.creditsCharged==='number'&&frame.creditsCharged>=0)).toBe(true);
      const billedChatId = voiceFrames(await evidence(page), 'start')[0].chatId;
      expect(billedChatId).toBeTruthy();
      await expect.poll(() => page.evaluate(async ({ apiUrl, chatId }) => {
        const response = await fetch(`${apiUrl}/v1/settings/usage/chat-entries?chat_id=${encodeURIComponent(chatId!)}`, { credentials: 'include' });
        if (!response.ok) return false;
        const data = await response.json();
        const charges = (data.entries ?? []).filter((entry: { skill_id: string }) => entry.skill_id === 'voice_call');
        return charges.length > 0 && charges.every((entry: { source: string; chat_id: string; model_used?: string }) =>
          entry.source === 'chat' && entry.chat_id === chatId && !!entry.model_used);
      }, { apiUrl: process.env.PLAYWRIGHT_TEST_API_URL, chatId: billedChatId }),
      { timeout: 30_000, intervals: [1000, 2000], message: 'Voice charges must appear under their bound chat with model attribution' }).toBe(true);
      await expect(page.getByTestId('voice-call-credits')).toHaveCount(0);
      expect(voiceFrames(await evidence(page), 'audio_stream_end')).toHaveLength(0);
      expect((await nativeVoiceInput(page)).detectorReady).toBe(0);
      releaseModel();
      await expect.poll(async () => (await nativeVoiceInput(page)).detectorReady, { timeout: 30_000 }).toBe(1);
      await expect(status).toHaveText('Speak to resume call.', { timeout: 15_000 });
      const idle = await evidence(page);
      expect(voiceFrames(idle, 'audio_stream_end')).toHaveLength(1);
      const verifiedQuietSamples = voiceFrames(idle, 'mic_audio').reduce((total, frame) => total + (frame.audioSamples ?? 0), 0)
        - (await nativeVoiceInput(page)).readyUploadedSamples;
      expect(verifiedQuietSamples).toBeGreaterThanOrEqual(16_000 * 5);
      await expect.poll(async () => (await evidence(page)).received.filter((frame) => frame.type === 'billing_activity').at(-1))
        .toMatchObject({ inputListening: false, processing: false });
      await assertActivityCounter(page,false);
      await assertActivityCounter(page,false);
      expect((await nativeVoiceInput(page)).localToneStarts).toBe(connectedTones);
      const timerAtIdle = await page.getByTestId('voice-call-timer').textContent();
      await expect(page.getByTestId('voice-call-credits')).toHaveCount(0);
      const idleCount = voiceFrames(idle, 'mic_audio').length;
      const idleSamples = (await nativeVoiceInput(page)).samples;
      await expect.poll(async () => (await nativeVoiceInput(page)).samples).toBeGreaterThan(idleSamples + 24_000);
      expect(voiceFrames(await evidence(page), 'mic_audio')).toHaveLength(idleCount);
      expect(voiceFrames(await evidence(page), 'audio_stream_end')).toHaveLength(1);
      await expect(page.getByTestId('voice-call-timer')).toHaveText(timerAtIdle!);

      // Real typed input keeps provider processing active while the local gate
      // remains idle. The exact isolated fixture waits for genuine resumed PCM.
      const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
      await editor.click();
      await page.keyboard.insertText(ACTIVITY_REQUEST);
      await page.getByTestId('composer-send-button').click();
      await expect(page.getByTestId('message-user').filter({ hasText: ACTIVITY_REQUEST })).toHaveCount(1);
      await expect.poll(async () => (await evidence(page)).received.filter((frame) => frame.type === 'billing_activity').at(-1))
        .toMatchObject({ inputListening: false, processing: true });
      await expect(status).toHaveText('OpenMates is working…');
      await assertActivityCounter(page,true);
      const workingSeconds=await activeCallSeconds(page);
      await expect.poll(()=>activeCallSeconds(page)).toBeGreaterThan(workingSeconds);
      expect(voiceFrames(await evidence(page), 'mic_audio')).toHaveLength(idleCount);

      await playNativeVoiceFixture(page);
      await expect.poll(()=>page.getByTestId('voice-call-waveform').locator('span').evaluateAll(nodes=>nodes.some(node=>Number(node.getAttribute('data-level'))>0)),{intervals:[25,50,100]}).toBe(true);
      await expect.poll(async () => voiceFrames(await evidence(page), 'mic_audio').length).toBeGreaterThan(idleCount);
      const resumed = await evidence(page);
      const resumedAudio = voiceFrames(resumed, 'mic_audio').slice(idleCount);
      const prefix = resumedAudio.filter((frame) => frame.audioBatch === resumedAudio[0].audioBatch);
      const prefixSamples = prefix.reduce((total, frame) => total + (frame.audioSamples ?? 0), 0);
      expect(prefixSamples).toBeGreaterThanOrEqual(16 * 300);
      expect(prefixSamples).toBeLessThanOrEqual(16 * 500);
      expect(prefix.some((frame) => frame.audioNonzero)).toBe(true);
      expect(resumed.sent.indexOf(voiceFrames(resumed, 'audio_stream_end')[0])).toBeLessThan(resumed.sent.indexOf(resumedAudio[0]));
      expect(voiceFrames(resumed, 'start')).toHaveLength(1);
      expect(voiceFrames(resumed, 'mic_audio').every((frame) => frame.socketId === start.socketId)).toBe(true);
      expect(resumed.received.filter((frame) => frame.type === 'ready' && frame.path === '/v1/voice-call')).toHaveLength(1);
      expect((await nativeVoiceInput(page)).captureRequests).toBe(1);
      await expect(page.getByTestId('message-assistant').filter({ hasText: ACTIVITY_REPLY })).toHaveCount(1);
      await expect(status).toHaveText('OpenMates is speaking…');

      expect((await nativeVoiceInput(page)).localToneStarts).toBe(connectedTones);

      // Already generated playback remains visible when manual mute stops input
      // and the server reports processing complete. Unmute remains accessible.
      await page.getByTestId('voice-call-mute').click();
      await expect(page.getByTestId('voice-call-mute')).toHaveAccessibleName('Unmute');
      await expect.poll(async () => (await nativeVoiceInput(page)).localToneStarts).toBeGreaterThan(connectedTones);
      const mutedTones = (await nativeVoiceInput(page)).localToneStarts;
      await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed', 'true');
      await expect.poll(async () => (await evidence(page)).received.filter((frame) => frame.type === 'billing_activity').at(-1))
        .toMatchObject({ inputListening: false, processing: false });
      await expect(status).toHaveText('OpenMates is speaking…');
      await assertActivityCounter(page,false);
      const mutedPlaybackTimer=await page.getByTestId('voice-call-timer').textContent();
      await expect(page.getByTestId('voice-call-credits')).toHaveCount(0);
      await expect(status).toHaveText('Microphone muted');
      const mutedCount = voiceFrames(await evidence(page), 'mic_audio').length;
      expect(voiceFrames(await evidence(page), 'audio_stream_end')).toHaveLength(2);
      await expect.poll(async () => (await nativeVoiceInput(page)).playing).toBe(false);
      await playNativeVoiceFixture(page, false);
      await expect.poll(async () => (await nativeVoiceInput(page)).playing, { timeout: 10_000 }).toBe(false);
      expect(voiceFrames(await evidence(page), 'mic_audio')).toHaveLength(mutedCount);
      expect(voiceFrames(await evidence(page), 'audio_stream_end')).toHaveLength(2);
      await expect(page.getByTestId('voice-call-timer')).toHaveText(mutedPlaybackTimer!);
      await expect(status).toHaveText('Microphone muted');
      await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed', 'true');
      expect((await nativeVoiceInput(page)).localToneStarts).toBe(mutedTones);
      await page.getByTestId('voice-call-mute').click();
      await expect(page.getByTestId('voice-call-mute')).toHaveAccessibleName('Mute');
      await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed', 'false');
      await expect.poll(async () => (await nativeVoiceInput(page)).localToneStarts).toBeGreaterThan(mutedTones);
      const unmutedTones = (await nativeVoiceInput(page)).localToneStarts;
      await expect.poll(async () => voiceFrames(await evidence(page), 'mic_audio').length).toBeGreaterThan(mutedCount);
      expect(voiceFrames(await evidence(page), 'start')).toHaveLength(1);
      expect((await nativeVoiceInput(page)).captureRequests).toBe(1);
      await page.getByTestId('voice-call-hangup').click();
      await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
      await expect.poll(async () => (await nativeVoiceInput(page)).localToneStarts).toBeGreaterThan(unmutedTones);
      await assertVoiceInputCleanup(page);
      expect(voiceFrames(await evidence(page), 'hangup').map((frame) => frame.socketId)).toEqual([start.socketId]);
    } finally { releaseModel(); }
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

  // contract-test: direct surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.fixed-binding,video-call.chat.transcripts,video-call.chat.call-events,video-call.chat.call-strip-layout,video-call.chat.activity-status,video-call.chat.typed-input,video-call.chat.compressed-context,video-call.chat.memories-and-focus,video-call.chat.skill-integration,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing,video-call.privacy,video-call.usage.provider-metering
  test('saves voice and typed turns encrypted, reloads them and reuses their context', async ({ page }, testInfo) => {
    test.setTimeout(300_000);
    await observeRealTransport(page);
    // A fresh account opens the welcome workspace; the voice button creates
    // its chat without requiring a text draft or a visible editor first.
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    await assertHeaderCallActions(page, false, false);
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status')).toContainText('Listening', { timeout: 45_000 });
    await expect(page.getByTestId('message-user').filter({ hasText: USER_SPEECH })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH })).toHaveCount(1);
    await assertHeaderCallActions(page, true, true);
    await assertSlimCallSurface(page);
    await assertActivityCounter(page,true);
    await expect.poll(async () => {
      const bar = await page.locator('[data-testid="voice-call-bar"]:visible').boundingBox();
      const history = await page.locator('[data-testid="chat-history-container"]:visible').boundingBox();
      return !!bar&&!!history&&bar.y>=history.y-1&&bar.y+bar.height<=history.y+history.height+1&&bar.x>=history.x-1&&bar.x+bar.width<=history.x+history.width+1;
    }).toBe(true);
    const chatId = await page.locator('[data-action="message-input"]').last().getAttribute('data-current-chat-id');
    expect(chatId).toMatch(/^[0-9a-f-]{36}$/i);
    // Collapsed recording is hidden; an expanded composer's control is disabled.
    await expect(page.locator('[data-testid="record-audio-button"]:visible:enabled, [data-testid="guest-cta-mic-button"]:visible:enabled')).toHaveCount(0);

    await page.locator('[data-testid="voice-call-mute"]:visible').click();
    await expect(page.locator('[data-testid="voice-call-mute"]:visible')).toHaveAttribute('aria-pressed', 'true');
    await expect.poll(async () => (await evidence(page)).sent.filter((event) => event.type === 'audio_stream_end').length).toBe(1);
    await expect.poll(async () => (await evidence(page)).received.filter((event) => event.type === 'billing_activity').at(-1))
      .toMatchObject({ inputListening: false, processing: false });
    await assertActivityCounter(page,false);
    await expect(page.getByTestId('voice-call-credits')).toHaveCount(0);
    const micCount = (await evidence(page)).sent.filter((event) => event.type === 'mic_audio').length;


    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await expect(editor).toBeVisible();
    await editor.click();
    await expect(page.getByTestId('record-audio-button')).toBeDisabled();
    await page.keyboard.insertText(PASTED_TEXT);
    await page.evaluate(() => {
      (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence.reconnectOnText = true;
    });
    await page.getByTestId('composer-send-button').click();
    await expect(page.getByTestId('message-user').filter({ hasText: PASTED_TEXT })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: 'I received your text' })).toHaveCount(1);
    expect((await evidence(page)).sent.filter(event=>event.type==='mic_audio').length).toBe(micCount);
    await expect.poll(async () => (await evidence(page)).received.some((event) => event.type === 'billing_activity' &&
      event.inputListening === false && event.processing === true)).toBe(true);
    await assertActivityCounter(page,false);
    await expect.poll(async () => (await evidence(page)).received.filter((event) => event.type === 'call_message_confirmed').length).toBeGreaterThanOrEqual(4);
    const transport = await evidence(page);
    const persisted = transport.sent.filter((event) => event.type === 'call_message_completed');
    expect(persisted.every((event) => (event.ciphertextLength ?? 0) > 30 && event.plaintext === false)).toBe(true);
    expect(transport.sent.filter((event) => event.type === 'text_input')).toHaveLength(1);
    expect(transport.sent.filter((event) => event.type === 'chat_message_added')).toHaveLength(0);
    expect(transport.received.filter((event) => event.type === 'call_message_rejected')).toHaveLength(0);
    expect(await page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
      .__voiceCallEvidence.reconnectInjected)).toBe(true);

    const messageIds = [...new Set(persisted.map((event) => event.messageId).filter((id): id is string => !!id))];
    expect(messageIds).toHaveLength(4);
    const rows = await page.evaluate(async (ids) => {
      const database = await new Promise<IDBDatabase>((resolve, reject) => {
        const open = indexedDB.open('chats_db');
        open.onsuccess = () => resolve(open.result);
        open.onerror = () => reject(open.error);
      });
      try {
        return await Promise.all(ids.map((id) => new Promise<{ encrypted: boolean; plaintext: boolean }>((resolve, reject) => {
          const request = database.transaction('messages', 'readonly').objectStore('messages').get(id);
          request.onsuccess = () => resolve({ encrypted: typeof request.result?.encrypted_content === 'string',
            plaintext: typeof request.result?.content === 'string' });
          request.onerror = () => reject(request.error);
        })));
      } finally { database.close(); }
    }, messageIds);
    expect(rows.every((row) => row.encrypted && !row.plaintext)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('voice-call-laptop.png') });

    // Closing the chat preserves its call; the actual Apps workspace Header
    // exposes the same bound call through its context-provided return pill.
    const boundReady=(await evidence(page)).received.find(event=>event.type==='ready'&&event.path==='/v1/voice-call');
    expect(boundReady?.callId).toBeTruthy();expect(boundReady?.socketId).toBeTruthy();
    await page.evaluate(()=>{
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      state.boundCaptureTracks=[...state.tracks];
    });
    await scrollChatHistoryToStart(page,testInfo);
    await page.getByTestId('chat-close-button').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await expect(page.getByTestId('voice-call-pill')).toHaveCount(1);
    await chooseAppsHome(page);
    await holdChatLookup(page,chatId!);
    try {
      await page.getByTestId('apps-route-header').getByTestId('voice-call-pill').click();
      await expectHeldChatLookup(page,'returnToVoiceCallChat');
      await expect(page.getByTestId('voice-call-pill')).toHaveCount(1);
      await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    } finally { await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.releaseChatLookup?.()); }
    await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
    await expect.poll(()=>new URL(page.url()).hash).toBe(`#chat-id=${chatId}`);
    await expect(page.getByTestId('message-user').filter({hasText:PASTED_TEXT})).toHaveCount(1);
    await expect(page.getByTestId('voice-call-bar')).toBeVisible();
    await expect(page.getByTestId('voice-call-pill')).toHaveCount(0);

    await page.setViewportSize({width:390,height:844});
    await page.locator('#settings-menu-toggle').click();
    await expect(page.getByTestId('settings-menu')).toHaveClass(/visible/);
    await expect(page.getByTestId('voice-call-pill')).toBeVisible();
    await holdChatLookup(page,chatId!);
    try {
      await page.getByTestId('voice-call-pill').click();
      await expectHeldChatLookup(page,'returnToVoiceCallChat');
      await expect(page.getByTestId('voice-call-pill')).toBeVisible();
    } finally { await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.releaseChatLookup?.()); }
    await expect(page.getByTestId('settings-menu')).not.toHaveClass(/visible/);
    await expect(page.getByTestId('voice-call-pill')).toHaveCount(0);
    await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed','true');
    await assertHeaderCallActions(page,true,true);
    await expectHeaderPointerAccess(page);
    await page.screenshot({path:testInfo.outputPath('voice-call-phone.png')});

    // A later native workspace selection supersedes a pending pill Return.
    // Preserve the real held IDB read and prove its stale completion cannot
    // pull the user out of their newly selected workspace or start another call.
    await scrollChatHistoryToStart(page,testInfo);
    await page.getByTestId('chat-close-button').click();
    await chooseAppsHome(page);
    await holdChatLookup(page,chatId!);
    try {
      await page.getByTestId('apps-route-header').getByTestId('voice-call-pill').click();
      await expectHeldChatLookup(page,'returnToVoiceCallChat');
      await chooseAppsHome(page);
    } finally { await page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.releaseChatLookup?.()); }
    await expect(page.getByTestId('apps-workspace-home')).toBeVisible();
    await expect.poll(()=>new URL(page.url()).hash.split('&')[0]).toBe('#apps');
    const awayTransport=await evidence(page);
    expect(voiceFrames(awayTransport,'start')).toHaveLength(1);
    expect(awayTransport.received.filter(event=>event.type==='ready'&&event.path==='/v1/voice-call').map(event=>event.callId)).toEqual([boundReady!.callId]);
    expect(voiceFrames(awayTransport,'hangup')).toHaveLength(0);
    await expect.poll(()=>page.evaluate(()=>{
      const state=(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence;
      return !!state.boundCaptureTracks?.length&&state.tracks.length===state.boundCaptureTracks.length&&
        state.tracks.every((track,index)=>track===state.boundCaptureTracks![index]&&track.readyState==='live');
    })).toBe(true);
    await page.getByTestId('apps-route-header').getByTestId('voice-call-pill').click();
    await expect(page.getByTestId('voice-call-bar')).toBeVisible();
    await expect(page.getByTestId('voice-call-pill')).toHaveCount(0);
    await expect.poll(()=>new URL(page.url()).hash).toBe(`#chat-id=${chatId}`);
    await expect(page.getByTestId('message-user').filter({hasText:PASTED_TEXT})).toHaveCount(1);
    await expect(page.getByTestId('voice-call-started')).toHaveCount(1);
    const startedTime=await page.getByTestId('voice-call-started').locator('time').getAttribute('datetime');
    await assertActivityCounter(page,false);
    const firstActiveSeconds=await activeCallSeconds(page);
    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await expect(page.getByTestId('voice-call-ended')).toHaveCount(1);
    const endedTime=await page.getByTestId('voice-call-ended').locator('time').getAttribute('datetime');
    await assertHeaderCallActions(page,false,true);
    expect(voiceFrames(await evidence(page),'hangup').map(event=>event.socketId)).toEqual([boundReady!.socketId]);
    await expect.poll(()=>page.evaluate(()=>(window as unknown as {__voiceCallEvidence:CallEvidence}).__voiceCallEvidence.tracks.every(track=>track.readyState==='ended'))).toBe(true);
    await assertCallHistoryDurable(page,chatId!,boundReady!.callId!,messageIds,[startedTime!,endedTime!],firstActiveSeconds);
    const lifecycleCiphertexts=(await evidence(page)).sent.filter(event=>event.type==='chat_system_message_added');
    expect(new Set(lifecycleCiphertexts.map(event=>event.messageId)).size).toBe(2);
    expect(lifecycleCiphertexts.every(event=>event.chatId===chatId&&event.plaintext===false&&(event.ciphertextLength??0)>30)).toBe(true);
    await evictOwnedCallRows(page,chatId!,boundReady!.callId!,messageIds);
    await page.reload();
    await expect(page.getByTestId('message-user').filter({ hasText: USER_SPEECH })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: ASSISTANT_SPEECH }).getByTestId('generated-by')).toContainText(/Gemini.*Live/i);
    await expect(page.getByTestId('message-user').filter({ hasText: PASTED_TEXT })).toHaveCount(1);
    await expect(page.getByTestId('message-assistant').filter({ hasText: 'I received your text' })).toHaveCount(1);
    await expect(page.getByTestId('voice-call-started')).toHaveCount(1);
    await expect(page.getByTestId('voice-call-ended')).toHaveCount(1);
    await expect(page.getByTestId('voice-call-started').locator('time')).toHaveAttribute('datetime',startedTime!);
    await expect(page.getByTestId('voice-call-ended').locator('time')).toHaveAttribute('datetime',endedTime!);
    await assertCallHistoryDurable(page,chatId!,boundReady!.callId!,messageIds,[startedTime!,endedTime!],firstActiveSeconds);
    // A reloaded phone uses the collapsed composer's native recording control.
    await expect(page.getByRole('button', { name: 'Record audio', exact: true })).toBeEnabled();

    const uncoveredIds = await seedVoiceContext(page, chatId!, messageIds.slice(0, 2));
    const storedSeed = (await evidence(page)).sent.filter((event) => event.type === 'encrypted_chat_metadata' && uncoveredIds.includes(event.messageId ?? ''));
    expect(storedSeed).toHaveLength(25);
    expect(storedSeed.every((event) => (event.ciphertextLength ?? 0) > 30 && event.plaintext === false)).toBe(true);
    await expectHeaderPointerAccess(page);
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status')).toContainText('Listening', { timeout: 45_000 });
    const resumed = (await evidence(page)).sent.find((event) => event.type === 'start');
    const resumedCallId = (await evidence(page)).received.find((event) => event.type === 'ready' && event.socketId === resumed?.socketId)?.callId;
    expect(resumedCallId).toBeTruthy();
    expect(resumed?.chatId).toBe(chatId);
    expect(resumed?.context?.some((turn) => turn.role === 'user' && turn.text.includes(PASTED_TEXT))).toBe(true);
    expect(resumed?.context?.filter((turn) => uncoveredIds.includes(turn.message_id ?? ''))).toHaveLength(25);
    expect(resumed?.context?.some((turn) => turn.text === UNCOVERED_CONTEXT_FACT)).toBe(true);
    expect(resumed?.summary?.endsWith(CHECKPOINT_FACT)).toBe(true);
    expect(resumed?.summary?.length).toBeGreaterThan(2_000);
    expect(resumed?.context?.some((turn) => messageIds.slice(0, 2).includes(turn.message_id ?? ''))).toBe(false);
    await page.locator('[data-testid="voice-call-mute"]:visible').click();
    const resumedEditor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await resumedEditor.click();
    await page.keyboard.insertText(STAGE_TWO_TEXT);
    await page.getByTestId('composer-send-button').click();
    await expect(page.getByTestId('btn-include')).toBeVisible({ timeout: 45_000 });
    // The ordinary shared consent surface must be interactive after a typed
    // call request, with usable audio controls and the selection unobstructed.
    const memoryToggle = page.getByTestId('memory-category-toggle-code-preferred_tech');
    const memoryCheckbox = memoryToggle.locator('input[type="checkbox"]');
    await waitForStickyCallControlsReady(page,testInfo);
    await assertSlimCallSurface(page);
    await expect(page.getByTestId('voice-call-mute')).toBeEnabled();
    await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed','true');
    await expect(page.getByTestId('voice-call-hangup')).toBeEnabled();
    for(const id of ['voice-call-mute','voice-call-hangup']) await expect.poll(()=>page.getByTestId(id).evaluate(element=>{
      const r=element.getBoundingClientRect();const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
      return hit===element||element.contains(hit);
    })).toBe(true);
    await expect.poll(() => memoryToggle.evaluate((element) => element.closest('[inert]') === null)).toBe(true);
    await expect(memoryToggle).toBeVisible();
    await expect(memoryCheckbox).toBeChecked();
    await memoryToggle.click();
    await expect(memoryCheckbox).not.toBeChecked();
    await expect(page.getByTestId('btn-include')).toBeDisabled();
    await memoryToggle.click();
    await expect(memoryCheckbox).toBeChecked();
    await expect(page.getByTestId('btn-include')).toBeEnabled();
    await page.screenshot({ path: testInfo.outputPath('voice-call-memory-consent-phone.png') });
    await page.getByTestId('btn-include').click();
    await expect(page.getByTestId('btn-include')).not.toBeVisible();
    await expect.poll(async () => [...new Set((await evidence(page)).received
      .filter((event) => event.type === 'voice_embed' && event.callId === resumedCallId && event.embedId)
      .map((event) => event.assistantMessageId).filter(Boolean))].length,
    { timeout: 60_000, message: 'The call artifacts must bind to exactly one issued assistant response' }).toBe(1);
    const responseIds = [...new Set((await evidence(page)).received
      .filter((event) => event.type === 'voice_embed' && event.callId === resumedCallId && event.embedId)
      .map((event) => event.assistantMessageId))];
    expect(responseIds).toHaveLength(1);
    expect(responseIds[0]).toBeTruthy();
    const stageReply = page.locator(`[data-testid="message-assistant"][data-message-id="${responseIds[0]}"]`);
    await expect(stageReply).toHaveCount(1, { timeout: 60_000 });
    await stageReply.scrollIntoViewIfNeeded();
    await expect(stageReply).toContainText(STAGE_TWO_REPLY, { timeout: 60_000 });
    await expect(page.getByTestId('message-assistant').filter({ hasText: STAGE_TWO_REPLY })).toHaveCount(1);
    await expandWebActivity(page, stageReply);
    await expect(stageReply.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"][data-embed-status="finished"]')).toBeVisible({ timeout: 45_000 });
    await expect(stageReply.getByTestId('search-preview-metadata-missing-message')).toHaveCount(0);
    await expect.poll(async () => (await evidence(page)).sent.filter((event) => event.type === 'voice_memory_response').length).toBe(1);
    const stageTransport = await evidence(page);
    expect(stageTransport.sent.filter((event) => event.type === 'app_settings_memories_confirmed')).toHaveLength(0);
    expect(stageTransport.sent.filter((event) => event.type === 'chat_message_added')).toHaveLength(0);
    const artifacts = stageTransport.received.filter((event) => event.type === 'voice_embed' && event.embedId);
    expect(artifacts.length).toBeGreaterThanOrEqual(1);
    expect([...new Set(artifacts.map((event) => event.assistantMessageId))]).toEqual(responseIds);
    expect(stageTransport.sent.some((event) => event.type === 'call_message_completed' && event.messageId === responseIds[0] && event.plaintext === false)).toBe(true);
    const durable = await page.evaluate(async ({ chatId, assistantId }) => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open('chats_db'); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
      const read = (store: string, id: string) => new Promise<Record<string, unknown>>((resolve, reject) => { const request = db.transaction(store, 'readonly').objectStore(store).get(id); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
      try { const [chat, response] = await Promise.all([read('chats', chatId), read('messages', assistantId)]);
        return { encryptedFocus: typeof chat.encrypted_active_focus_id === 'string',
          encryptedResponse: typeof response.encrypted_content === 'string', plaintext: 'content' in response,
          linkedUser: typeof response.user_message_id === 'string' }; } finally { db.close(); }
    }, { chatId: chatId!, assistantId: responseIds[0]! });
    expect(durable).toEqual({ encryptedFocus: true, encryptedResponse: true, plaintext: false, linkedUser: true });
    await expect.poll(async () => (await evidence(page)).sent.some((event) =>
      event.type === 'voice_action_completed_confirmed' && event.messageId === responseIds[0]),
    { timeout: 45_000, message: 'Committed artifacts must reach durable encrypted storage before their receipt ACK' }).toBe(true);
    // This call adds enough real completed history to require shared compression.
    // Verify encrypted storage and provider adoption before ending the session;
    // a cancelled pending checkpoint must not silently discard those facts.
    await expect.poll(async () => (await evidence(page)).received.some((event) =>
      event.type === 'voice_context_resumed' && event.callId === resumedCallId),
    { timeout: 60_000, message: 'The completed call context must be durably checkpointed and adopted before hangup' }).toBe(true);
    const compressedTransport = await evidence(page);
    const adopted = compressedTransport.received.find((event) => event.type === 'voice_context_resumed' && event.callId === resumedCallId)!;
    const compression = compressedTransport.received.find((event) => event.type === 'voice_compression' && event.checkpointId === adopted.checkpointId);
    expect(compression?.coveredMessageIds?.length).toBeGreaterThan(0);
    expect(compression?.compressedMessageCount).toBe(compression?.coveredMessageIds?.length);
    expect(compression?.coveredMessageIds).toEqual([...new Set(compression!.coveredMessageIds)].sort());
    const snapshotIndex = compressedTransport.received.findIndex((event) => event.type === 'voice_compression_started' && event.snapshotId === compression?.snapshotId);
    expect(snapshotIndex).toBeGreaterThanOrEqual(0);
    const billingBeforeCompression = compressedTransport.received.slice(0, snapshotIndex)
      .filter((event) => event.type === 'billing_activity' && event.callId === resumedCallId).at(-1);
    expect(billingBeforeCompression, 'Paid compression must report processing before its snapshot starts').toMatchObject({ processing: true });
    const snapshot = compressedTransport.received[snapshotIndex];
    const sourceRecords = new Map((resumed?.context ?? []).map((turn) => [turn.message_id, { role: turn.role, createdAt: turn.created_at }]));
    for (const event of compressedTransport.received.slice(0, snapshotIndex)) {
      if (event.type === 'transcript' && event.callId === resumedCallId && event.final && event.messageId) sourceRecords.set(event.messageId,
        { role: event.role!, createdAt: event.createdAt });
    }
    expect(snapshot.sourceMessageIds?.every((id) => sourceRecords.has(id))).toBe(true);
    const expectedPrefix = snapshot.sourceMessageIds!.filter((id) => sourceRecords.get(id)!.createdAt! <= compression!.boundaryTimestamp!).sort();
    expect(compression?.coveredMessageIds).toEqual(expectedPrefix);
    const retained = snapshot.sourceMessageIds!.filter((id) => !expectedPrefix.includes(id));
    expect(retained.length).toBeGreaterThan(0);
    expect(retained.every((id) => sourceRecords.get(id)!.createdAt! > compression!.boundaryTimestamp!)).toBe(true);
    const protectedAssistant = snapshot.sourceMessageIds!.filter((id) => sourceRecords.get(id)!.role === 'assistant').at(-1);
    expect(protectedAssistant).toBeTruthy();
    expect(retained).toContain(protectedAssistant);
    expect(compression?.coveredMessageIds).toContain(uncoveredIds[0]);
    expect(uncoveredIds.every((id) => expectedPrefix.includes(id) || retained.includes(id))).toBe(true);
    expect(compression?.coveredMessageIds).not.toContain(responseIds[0]);
    expect(compressedTransport.sent).toContainEqual(expect.objectContaining({ type: 'store_chat_compression_checkpoint',
      checkpointId: adopted.checkpointId, plaintext: false }));
    expect(compressedTransport.received).toContainEqual(expect.objectContaining({ type: 'chat_compression_checkpoint_stored', checkpointId: adopted.checkpointId }));
    expect(compressedTransport.sent).toContainEqual(expect.objectContaining({ type: 'voice_compression_confirmed', checkpointId: adopted.checkpointId }));
    const storedCheckpoint = await page.evaluate(async (checkpointId) => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open('chats_db'); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
      try {
        return await new Promise<{ encrypted: boolean; plaintext: boolean; coveredManifest: boolean }>((resolve, reject) => {
          const request = db.transaction('chat_compression_checkpoints', 'readonly').objectStore('chat_compression_checkpoints').get(checkpointId);
          request.onsuccess = () => resolve({ encrypted: typeof request.result?.encrypted_summary === 'string' && request.result.encrypted_summary.length > 30,
            plaintext: 'summary' in (request.result ?? {}), coveredManifest: 'covered_message_ids' in (request.result ?? {}) });
          request.onerror = () => reject(request.error);
        });
      } finally { db.close(); }
    }, adopted.checkpointId!);
    expect(storedCheckpoint).toEqual({ encrypted: true, plaintext: false, coveredManifest: false });
    await page.screenshot({ path: testInfo.outputPath('voice-call-stage-two-phone.png') });
    await page.locator('[data-testid="voice-call-hangup"]:visible').click();
    await assertCallHistoryDurable(page,chatId!,resumedCallId!);
    await evictOwnedCallRows(page,chatId!,resumedCallId!);
    await page.reload();
    await showForgottenHistory(page);
    await assertCallHistoryDurable(page,chatId!,resumedCallId!);
    const reloadedReply = page.locator(`[data-testid="message-assistant"][data-message-id="${responseIds[0]}"]`);
    await expect(reloadedReply).toHaveCount(1, { timeout: 45_000 });
    await reloadedReply.scrollIntoViewIfNeeded();
    await expect(reloadedReply).toContainText(STAGE_TWO_REPLY, { timeout: 45_000 });
    await expect(page.getByTestId('message-assistant').filter({ hasText: STAGE_TWO_REPLY })).toHaveCount(1);
    await expect(reloadedReply).toHaveAttribute('data-message-id', responseIds[0]!);
    await expandWebActivity(page, reloadedReply);
    await expect(reloadedReply.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"][data-embed-status="finished"]')).toBeVisible({ timeout: 45_000 });
    await expect(reloadedReply.getByTestId('search-preview-metadata-missing-message')).toHaveCount(0);

    // End the next call on the real committed-action receipt, before the
    // deliberately delayed external speech. Completion must survive teardown.
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status')).toContainText('Listening', { timeout: 45_000 });
    const coldStart = (await evidence(page)).sent.find((event) => event.type === 'start');
    const coldReady = (await evidence(page)).received.find((event) => event.type === 'ready' && event.socketId === coldStart?.socketId);
    expect(coldReady?.callId).toBeTruthy();
    expect(coldReady?.socketId).toBeTruthy();
    expect(coldReady?.callId).not.toBe(resumedCallId);
    expect(coldStart?.summary).toContain(CHECKPOINT_FACT);
    expect(coldStart?.summary).toContain(UNCOVERED_CONTEXT_FACT);
    const coldContext = [coldStart?.summary ?? '', ...(coldStart?.context ?? []).map((turn) => turn.text)].join('\n');
    const seededFacts = resumed!.context!.filter((turn) => uncoveredIds.includes(turn.message_id ?? '')).map((turn) => turn.text);
    expect(seededFacts.every((fact) => coldContext.includes(fact))).toBe(true);
    await page.locator('[data-testid="voice-call-mute"]:visible').click();
    await page.evaluate((owner) => {
      (window as unknown as { __voiceCallEvidence: CallEvidence }).__voiceCallEvidence.hangupOnCommittedAction = owner;
    }, { callId: coldReady!.callId!, socketId: coldReady!.socketId! });
    const finalEditor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await finalEditor.click(); await page.keyboard.insertText(STAGE_TWO_TEXT);
    await page.getByTestId('composer-send-button').click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
      .__voiceCallEvidence.committedHangupInjected ?? false), { timeout: 60_000 }).toBe(true);
    await expect(page.locator('[data-testid="voice-call-bar"]:visible')).toHaveCount(0);
    const committed = await page.evaluate(() => (window as unknown as { __voiceCallEvidence: CallEvidence })
      .__voiceCallEvidence.committedHangupReceipt);
    expect(committed?.assistantMessageId).toBeTruthy(); expect(committed?.embedId).toBeTruthy();
    expect(committed?.callId).toBe(coldReady!.callId);
    expect(committed?.assistantMessageId).not.toBe(responseIds[0]);
    expect((await evidence(page)).received).toContainEqual(committed);
    const committedAssistant = page.locator(`[data-testid="message-assistant"][data-message-id="${committed!.assistantMessageId}"]`);
    await expect(committedAssistant).toHaveCount(1);
    await committedAssistant.scrollIntoViewIfNeeded();
    await expandWebActivity(page, committedAssistant);
    const committedCard = page.locator(`[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"][data-embed-id$="${committed!.embedId}"]`);
    await expect(committedCard).toBeVisible({ timeout: 45_000 });
    await expect(committedCard).toHaveAttribute('data-embed-status', 'finished');
    await expect(committedAssistant.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]')).toHaveCount(1);
    await expect(committedAssistant).not.toContainText(STAGE_TWO_REPLY);
    await expect.poll(async () => (await evidence(page)).sent.some((event) =>
      event.type === 'voice_action_completed_confirmed' && event.messageId === committed!.assistantMessageId),
    { timeout: 45_000, message: 'Committed artifacts must reach durable encrypted storage before their receipt ACK' }).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('voice-call-committed-result-after-hangup.png') });
    await assertCallHistoryDurable(page,chatId!,coldReady!.callId!);
    await evictOwnedCallRows(page,chatId!,coldReady!.callId!);
    await page.reload();
    await showForgottenHistory(page);
    const recoveredAssistant = page.locator(`[data-testid="message-assistant"][data-message-id="${committed!.assistantMessageId}"]`);
    await expect(recoveredAssistant).toHaveCount(1);
    await recoveredAssistant.scrollIntoViewIfNeeded();
    await expandWebActivity(page, recoveredAssistant);
    const recoveredCard = page.locator(`[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"][data-embed-id$="${committed!.embedId}"]`);
    await expect(recoveredCard).toBeVisible({ timeout: 45_000 });
    await expect(recoveredCard).toHaveAttribute('data-embed-status', 'finished');
    await expect(page.getByTestId('message-assistant').filter({ has: recoveredCard })).toHaveCount(1);

    // Native call preparation must show one usable error, rather than opening
    // a provider or silently dropping older facts when context cannot fit.
    const overLimitIds = await seedVoiceContext(page, chatId!, messageIds.slice(0, 2), 31);
    expect(overLimitIds).toHaveLength(31);
    await assertCallHistoryDurable(page,chatId!,coldReady!.callId!);
    const lifecycleBeforeRefusal=new Set((await evidence(page)).sent.filter(event=>event.type==='chat_system_message_added').map(event=>event.messageId)).size;
    const admittedBeforeRefusal = (await evidence(page)).sent.filter((event) => event.type === 'start').length;
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.locator('[data-testid="voice-call-bar"]:visible')).toHaveCount(1);
    await expect(page.getByTestId('voice-call-error')).toHaveText('This chat has more context than a voice call can load. Continue with text.');
    expect((await evidence(page)).sent.filter((event) => event.type === 'start')).toHaveLength(admittedBeforeRefusal);
    expect(new Set((await evidence(page)).sent.filter(event=>event.type==='chat_system_message_added').map(event=>event.messageId)).size).toBe(lifecycleBeforeRefusal);
    await expect(page.locator('[data-testid="voice-call-hangup"]:visible')).toHaveAccessibleName('Close');
    await page.screenshot({ path: testInfo.outputPath('voice-call-context-too-large-phone.png') });
    await page.locator('[data-testid="voice-call-hangup"]:visible').click();
    await expect(page.locator('[data-testid="voice-call-bar"]:visible')).toHaveCount(0);
    await assertHeaderCallActions(page, false, true);
  });
});
