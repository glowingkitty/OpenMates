import { getApiUrl } from '../config/api';
import { getWebSocketToken } from '../utils/cookies';
import { getSessionId } from '../utils/sessionId';

export const REALTIME_TRANSCRIPTION_MODEL = 'voxtral-mini-transcribe-realtime-2602';
const TARGET_SAMPLE_RATE = 16_000;
const MAX_QUEUED_CHUNKS = 96;
const WS_TOKEN_REFRESH_LEEWAY_SECONDS = 30;

export interface RealtimeTranscriptionResult {
  transcript: string;
  language?: string;
  model: string;
}

export interface RealtimeCorrectionResult extends RealtimeTranscriptionResult {
  title?: string;
  transcriptOriginal: string;
  transcriptCorrected?: string;
  useCorrected: boolean;
  correctionModel?: string;
}

export interface AudioRealtimeTranscriptionHandle {
  transcription: Promise<RealtimeTranscriptionResult>;
  correction: Promise<RealtimeCorrectionResult>;
  finish(): void;
  cancel(): void;
  setChatId(chatId: string): void;
}

interface StartOptions {
  onTranscript?: (transcript: string) => void;
  onStatus?: (status: 'connecting' | 'listening' | 'correcting' | 'failed') => void;
}

function websocketUrl(token: string | null): string {
  const url = new URL(
    getApiUrl().replace(/^http/, 'ws') + '/v1/apps/audio/realtime-transcription',
  );
  url.searchParams.set('sessionId', getSessionId());
  if (token) url.searchParams.set('token', token);
  return url.toString();
}

export function websocketTokenNeedsRefresh(
  token: string | null,
  nowSeconds = Date.now() / 1000,
): boolean {
  if (!token) return true;
  const parts = token.split(':', 3);
  // Preserve compatibility with non-HMAC development tokens. Production HMAC
  // tokens always use <hash>:<expiry>:<signature>.
  if (parts.length !== 3) return false;
  const expiry = Number(parts[1]);
  return !Number.isFinite(expiry) || expiry <= nowSeconds + WS_TOKEN_REFRESH_LEEWAY_SECONDS;
}

async function freshWebSocketToken(): Promise<string> {
  let token = getWebSocketToken();
  if (websocketTokenNeedsRefresh(token)) {
    const { checkAuth } = await import('../stores/authSessionActions');
    const authenticated = await checkAuth(undefined, true);
    if (!authenticated) throw new Error('Audio transcription session expired');
    token = getWebSocketToken();
  }
  if (!token || websocketTokenNeedsRefresh(token)) {
    throw new Error('Audio transcription authentication unavailable');
  }
  return token;
}

function pcm16Base64(samples: Float32Array): string {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

export function downsampleAudio(input: Float32Array, sourceRate: number): Float32Array {
  if (sourceRate === TARGET_SAMPLE_RATE) return input;
  const ratio = sourceRate / TARGET_SAMPLE_RATE;
  const output = new Float32Array(Math.max(1, Math.floor(input.length / ratio)));
  for (let outputIndex = 0; outputIndex < output.length; outputIndex += 1) {
    const start = Math.floor(outputIndex * ratio);
    const end = Math.min(input.length, Math.max(start + 1, Math.floor((outputIndex + 1) * ratio)));
    let sum = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) sum += input[inputIndex];
    output[outputIndex] = sum / (end - start);
  }
  return output;
}

export function startAudioRealtimeTranscription(
  stream: MediaStream,
  options: StartOptions = {},
): AudioRealtimeTranscriptionHandle {
  let socket: WebSocket | null = null;
  let context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let processor: ScriptProcessorNode | null = null;
  let silentGain: GainNode | null = null;
  let ready = false;
  let finished = false;
  let cancelled = false;
  let settledTranscription = false;
  let settledCorrection = false;
  let transcript = '';
  let rawResult: RealtimeTranscriptionResult | null = null;
  let pendingChatId: string | null = null;
  const queuedChunks: string[] = [];

  let resolveTranscription!: (value: RealtimeTranscriptionResult) => void;
  let rejectTranscription!: (reason: Error) => void;
  let resolveCorrection!: (value: RealtimeCorrectionResult) => void;
  let rejectCorrection!: (reason: Error) => void;
  const transcription = new Promise<RealtimeTranscriptionResult>((resolve, reject) => {
    resolveTranscription = resolve;
    rejectTranscription = reject;
  });
  const correction = new Promise<RealtimeCorrectionResult>((resolve, reject) => {
    resolveCorrection = resolve;
    rejectCorrection = reject;
  });
  // Consumers attach after MediaRecorder has emitted its blob. Prevent an early
  // connection failure from surfacing as an unhandled rejection meanwhile.
  void transcription.catch(() => undefined);
  void correction.catch(() => undefined);

  const stopAudioGraph = () => {
    processor?.disconnect();
    source?.disconnect();
    silentGain?.disconnect();
    processor = null;
    source = null;
    silentGain = null;
    const closing = context;
    context = null;
    if (closing && closing.state !== 'closed') void closing.close().catch(() => undefined);
  };

  const fail = (message: string) => {
    if (settledTranscription && settledCorrection) return;
    cancelled = true;
    options.onStatus?.('failed');
    stopAudioGraph();
    const error = new Error(message);
    if (!settledTranscription) {
      settledTranscription = true;
      rejectTranscription(error);
    }
    if (!settledCorrection) {
      settledCorrection = true;
      rejectCorrection(error);
    }
    if (socket?.readyState === WebSocket.OPEN) socket.close(1011, 'realtime failed');
  };

  const attachSocketHandlers = (activeSocket: WebSocket) => {
    activeSocket.onmessage = (event) => {
      const message = JSON.parse(String(event.data));
      switch (message.type) {
        case 'session.ready':
          ready = true;
          options.onStatus?.('listening');
          while (queuedChunks.length && activeSocket.readyState === WebSocket.OPEN) {
            activeSocket.send(JSON.stringify({ type: 'input_audio.append', audio: queuedChunks.shift() }));
          }
          if (pendingChatId && activeSocket.readyState === WebSocket.OPEN) {
            activeSocket.send(JSON.stringify({ type: 'session.metadata', chat_id: pendingChatId }));
          }
          if (finished && activeSocket.readyState === WebSocket.OPEN) {
            activeSocket.send(JSON.stringify({ type: 'input_audio.end' }));
          }
          break;
        case 'transcription.text.delta':
          transcript += String(message.text ?? '');
          options.onTranscript?.(transcript.trim());
          break;
        case 'transcription.done': {
          transcript = String(message.transcript ?? transcript).trim();
          options.onTranscript?.(transcript);
          rawResult = {
            transcript,
            language: message.language || undefined,
            model: String(message.model || REALTIME_TRANSCRIPTION_MODEL),
          };
          if (!settledTranscription) {
            settledTranscription = true;
            resolveTranscription(rawResult);
          }
          break;
        }
        case 'correction.started':
          options.onStatus?.('correcting');
          break;
        case 'correction.done':
          if (!rawResult) break;
          if (!settledCorrection) {
            settledCorrection = true;
            resolveCorrection({
              ...rawResult,
              title: message.title || undefined,
              transcript: String(message.transcript || rawResult.transcript),
              transcriptOriginal: rawResult.transcript,
              transcriptCorrected: String(message.transcript || '') || undefined,
              useCorrected: true,
              correctionModel: message.correction_model || undefined,
            });
          }
          activeSocket.close(1000, 'complete');
          break;
        case 'correction.failed':
          if (rawResult && !settledCorrection) {
            settledCorrection = true;
            resolveCorrection({
              ...rawResult,
              transcriptOriginal: rawResult.transcript,
              useCorrected: false,
            });
          }
          activeSocket.close(1000, 'complete');
          break;
        case 'session.error':
          fail(String(message.message || 'Realtime transcription failed'));
          break;
      }
    };
    activeSocket.onerror = () => fail('Realtime transcription connection failed');
    activeSocket.onclose = () => {
      stopAudioGraph();
      if (!cancelled && !settledCorrection) fail('Realtime transcription ended early');
    };
  };

  const openSocket = (token: string) => {
    if (cancelled) return;
    const activeSocket = new WebSocket(websocketUrl(token));
    socket = activeSocket;
    attachSocketHandlers(activeSocket);
  };

  try {
    options.onStatus?.('connecting');
    const currentToken = getWebSocketToken();
    if (websocketTokenNeedsRefresh(currentToken)) {
      void freshWebSocketToken().then(openSocket).catch((error) => {
        fail(error instanceof Error ? error.message : 'Realtime transcription authentication failed');
      });
    } else {
      openSocket(currentToken!);
    }
    const audioWindow = window as typeof window & { webkitAudioContext?: typeof AudioContext };
    const AudioContextConstructor = window.AudioContext ?? audioWindow.webkitAudioContext;
    if (!AudioContextConstructor) throw new Error('Web Audio API is unavailable');
    context = new AudioContextConstructor();
    source = context.createMediaStreamSource(stream);
    processor = context.createScriptProcessor(4096, 1, 1);
    silentGain = context.createGain();
    silentGain.gain.value = 0;
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);
    processor.onaudioprocess = (event) => {
      if (finished || cancelled) return;
      const samples = downsampleAudio(event.inputBuffer.getChannelData(0), event.inputBuffer.sampleRate);
      const audio = pcm16Base64(samples);
      if (ready && socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input_audio.append', audio }));
      } else if (queuedChunks.length < MAX_QUEUED_CHUNKS) {
        queuedChunks.push(audio);
      } else {
        cancelled = true;
        fail('Realtime transcription did not become ready in time');
        socket?.close(1011, 'audio queue full');
      }
    };
    if (context.state === 'suspended') void context.resume();

  } catch (error) {
    fail(error instanceof Error ? error.message : 'Realtime transcription failed');
  }

  return {
    transcription,
    correction,
    finish() {
      if (finished || cancelled) return;
      finished = true;
      stopAudioGraph();
      if (ready && socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input_audio.end' }));
      }
    },
    cancel() {
      if (cancelled) return;
      stopAudioGraph();
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'session.cancel' }));
      }
      fail('Realtime transcription cancelled');
    },
    setChatId(chatId: string) {
      pendingChatId = chatId;
      if (ready && socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'session.metadata', chat_id: chatId }));
      }
    },
  };
}
