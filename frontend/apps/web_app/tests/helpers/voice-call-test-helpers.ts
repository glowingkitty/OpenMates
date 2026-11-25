/** Shared browser-side voice fixtures for the voice-call web specs (native microphone stand-in and call evidence types). */
import type { Page } from '@playwright/test';

export interface SocketObservation {
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
  chatStartClipText?: boolean;
  kind?: string;
  speechStatus?: string;
  clipId?: string;
  promptKind?: string;
  promptRequestId?: string;
  promptClips?: string[];
  speechErrorCode?: string;
  speechAction?: 'request'|'generate'|'retry'|'cancel'|'delete';
  recoveryOperation?: string;
  jobId?: string;
  recordId?: string;
  expectedMessagesV?: number;
  committedMessagesV?: number;
  recoveryMessagesV?: number;
  persistenceState?: 'LEASED'|'TERMINAL'|'ACKNOWLEDGED';
  windowStatus?: number;
  windowOutcome?: 'response'|'failed'|'invalid';
  windowPurpose?: 'version'|'assistant_row';
  requestedAt?: number;
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
  pasted?: boolean;
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
  creditsAccrued?: number;
  sttDuration?: number;
  checkpointId?: string;
  coveredCount?: number;
  compressedMessageCount?: number;
  sourceMessageIds?: string[];
  coveredMessageIds?: string[];
  snapshotId?: string;
  boundaryTimestamp?: number;
  createdAt?: number;
  final?: boolean;
  pendingReason?: 'incomplete'|'uncertain';
  textLength?: number;
  expectedReply?: boolean;
  context?: Array<{ role: string; text: string; message_id?: string; created_at?: number }>;
}
export interface TurnDeliveryObservation {
  callId?: string; chatId?: string; turnId?: string; phase: string; reason?: string; observedAt: number;
  foreground?: { visible: boolean; focused: boolean };
  failure?: {errorClass?:string;errorCode?:string;httpStatus?:number;module?:string;line?:number};
}
export interface HeldSpeechEvidence {
  audio:HTMLAudioElement|null; segmentId:string|null; source:string|null; offset:number;
  firstProgressAt:number|null; playCallsAtHold:number; playCalls:number;
  sourceMse:boolean; beforeProviderEnd:boolean; sequence:number|null;
  nativeErrors:Array<{code:number;observedAt:number}>;
  handoffProgress?:{messageId:string;segmentId:string;audioId:number;observedAt:number;currentTime:number};
}
export interface CallEvidence {
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
  voiceSocket?: WebSocket;
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

export interface SpeechPrimeObservation {
  audioId: number;
  observedAt: number;
  userActivationActive: boolean;
  gestureDispatchActive: boolean;
  gesture: 'start'|'consent'|null;
  gestureAt: number|null;
}
export interface NativeVoiceInputEvidence {
  speechPrimes: SpeechPrimeObservation[];
  speechAcknowledgementPosts: number[];
  speechAudioId: (audio: HTMLMediaElement) => number;
  nativeTracks: MediaStreamTrack[];
  outputTracks: MediaStreamTrack[];
  contexts: AudioContext[];
  pageContexts: AudioContext[];
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
  failDetector: () => void;
  readyUploadedSamples: number;
  error: boolean;
  play: (short: boolean) => void;
}

/** Feed the public WAV through a genuine microphone/WebAudio stream at native cadence. */
export async function installNativeVoiceInput(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const state: NativeVoiceInputEvidence = {
      speechPrimes: [], speechAcknowledgementPosts: [], speechAudioId: () => 0,
      nativeTracks: [], outputTracks: [], contexts: [], pageContexts: [], localToneStarts: 0, samples: 0, sampleRate: 0,
      capturedSpeech: false, capturedQuietSamples: 0,
      captureRequests: 0, interruptOnPermission: false, permissionInterruptions: 0, speechReady: false, playing: false, workersCreated: 0,
      workersTerminated: 0, detectorReady: 0, failDetector: () => {}, readyUploadedSamples: 0, error: false, play: () => {},
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
        // Event sounds open one page-lifetime output from the capture-phase
        // pointerdown/keydown unlock (services/eventSounds.ts), before the click
        // that starts a call. It is not call audio, so call cleanup never owns it.
        const eventType = (window.event as Event | undefined)?.type;
        if (eventType === 'pointerdown' || eventType === 'keydown') state.pageContexts.push(context);
        else state.contexts.push(context);
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
          state.failDetector = () => worker.dispatchEvent(new ErrorEvent('error'));
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
        // Both excerpts contain genuine voiced input. The ordinary two-second
        // slice exceeds the split-STT continuation threshold while completing
        // within existing five-second playback assertions; the short slice
        // deliberately remains below that threshold for the pending-pause case.
        player.start(0, 0.75, short ? 0.35 : 2);
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

export async function nativeVoiceInput(page: Page) {
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
