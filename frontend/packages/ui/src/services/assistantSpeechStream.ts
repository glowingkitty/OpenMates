// Transient MP3 transport. No plaintext audio is cached or persisted here.
export interface AssistantSpeechAudioEvent {
  chat_id: string;
  message_id: string;
  voice_call_id: string;
  segment_id: string;
  sequence: number;
  kind: "voice_prose_clause" | "waiting_confirmation" | "voice_prose_turn";
  source_version: number;
  execution_version: number;
  attempt_id: string;
  phase: "start" | "chunk" | "end" | "error" | "alignment";
  clause_timings?: AssistantSpeechClauseTiming[];
  chunk_index: number;
  audio_data?: string;
  mime_type: "audio/mpeg";
}

export interface AssistantSpeechClauseTiming {
  segment_id: string; sequence: number; start_ms: number; end_ms: number;
}

export interface AssistantSpeechStreamSource {
  readonly url: string;
  readonly complete: boolean;
  readonly requiresRemotePlaybackDisabled?: boolean;
  dispose(): void;
  fail(): void;
}

export const MAX_SPEECH_STREAM_BYTES = 4 * 1024 * 1024;
export const MAX_SPEECH_STREAM_PENDING_BYTES = 512 * 1024;
export const MAX_SPEECH_STREAM_CHUNK_BYTES = 128 * 1024;
export const MAX_SPEECH_STREAM_RETAINED_BYTES = 16 * 1024 * 1024;
const STREAM_IDLE_MS = 15_000;
export const MAX_TURN_STREAM_BYTES = 16 * 1024 * 1024;
const MAX_TURN_LIFETIME_MS = 600_000;

export function validClauseTimings(value: unknown): value is AssistantSpeechClauseTiming[] {
  if (!Array.isArray(value) || value.length > 1024) return false;
  let previousSequence = -1, previousEnd = 0;
  const ids = new Set<string>();
  return value.every(row => {
    if (!row || Object.keys(row).sort().join(",") !== "end_ms,segment_id,sequence,start_ms"
      || typeof row.segment_id !== "string" || !/^(?:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(row.segment_id)
      || ids.has(row.segment_id) || !Number.isSafeInteger(row.sequence) || row.sequence <= previousSequence || row.sequence > 65535
      || !Number.isSafeInteger(row.start_ms) || !Number.isSafeInteger(row.end_ms) || row.start_ms < previousEnd
      || row.end_ms <= row.start_ms || row.end_ms > MAX_TURN_LIFETIME_MS) return false;
    previousSequence = row.sequence; previousEnd = row.end_ms; ids.add(row.segment_id); return true;
  });
}

/** iPhone exposes ManagedMediaSource rather than the desktop MediaSource API. */
function speechMediaSource(): { constructor: typeof MediaSource; managed: boolean } | null {
  if (typeof URL.createObjectURL !== "function") return null;
  const managed = (globalThis as typeof globalThis & { ManagedMediaSource?: typeof MediaSource }).ManagedMediaSource;
  for (const candidate of [
    { constructor: typeof MediaSource === "undefined" ? undefined : MediaSource, managed: false },
    { constructor: managed, managed: true },
  ]) {
    try {
      if (typeof candidate.constructor?.isTypeSupported === "function" && candidate.constructor.isTypeSupported("audio/mpeg")) {
        return { constructor: candidate.constructor, managed: candidate.managed };
      }
    } catch { /* Try the other native API when a codec probe is unavailable. */ }
  }
  return null;
}

export function supportsAssistantSpeechStream(): boolean { return speechMediaSource() !== null; }

export function isAssistantSpeechAudioEvent(value: unknown): value is AssistantSpeechAudioEvent {
  if (!value || typeof value !== "object") return false;
  const event = value as Partial<AssistantSpeechAudioEvent>;
  return [event.chat_id, event.message_id, event.voice_call_id, event.segment_id].every(
    (id) => typeof id === "string" && id.length > 0 && id.length <= 128,
  ) && ["voice_prose_clause", "waiting_confirmation", "voice_prose_turn"].includes(event.kind ?? "") && event.mime_type === "audio/mpeg"
    && typeof event.attempt_id === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(event.attempt_id)
    && Number.isSafeInteger(event.sequence)
    && (event.kind === "waiting_confirmation" ? event.sequence === -1 : event.kind === "voice_prose_turn" ? event.sequence === 0 : event.sequence! >= 0 && event.sequence! <= 65_535)
    && Number.isSafeInteger(event.source_version) && event.source_version! >= 1
    && Number.isSafeInteger(event.execution_version) && event.execution_version! >= 1
    && Number.isSafeInteger(event.chunk_index) && event.chunk_index! >= 0
    && event.chunk_index! <= (event.phase === "chunk" ? 4095 : 4096)
    && ["start", "chunk", "end", "error", "alignment"].includes(event.phase ?? "")
    && (event.phase === "alignment" ? event.kind === "voice_prose_turn" && validClauseTimings(event.clause_timings) : event.clause_timings === undefined)
    && (event.phase === "chunk" ? typeof event.audio_data === "string"
      && event.audio_data.length > 0 && event.audio_data.length <= Math.ceil(MAX_SPEECH_STREAM_CHUNK_BYTES / 3) * 4
      : event.audio_data === undefined);
}

/** One provider attempt. Missing bytes fail visibly and never grant heard coverage. */
export class AssistantSpeechStream implements AssistantSpeechStreamSource {
  // Charge accepted bytes until disposal, including bytes already appended to
  // a native SourceBuffer. This also bounds unusual manual navigation patterns.
  private static retainedBytes = 0;
  readonly url: string;
  complete = false;
  private media: MediaSource | null;
  readonly requiresRemotePlaybackDisabled: boolean;
  private buffer: SourceBuffer | null = null;
  private chunks: Uint8Array<ArrayBuffer>[] = [];
  private pendingBytes = 0;
  private totalBytes = 0;
  private nextIndex = 0;
  private providerEnded = false;
  private disposed = false;
  private failed = false;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private lifetimeTimer: ReturnType<typeof setTimeout> | undefined;
  private turn = false;

  get active(): boolean { return !this.disposed; }

  constructor(private readonly onFailure: () => void, turn = false) {
    const selected = speechMediaSource();
    if (!selected) throw new Error("Live speech playback is not supported in this browser.");
    this.media = new selected.constructor();
    this.requiresRemotePlaybackDisabled = selected.managed;
    this.turn = turn;
    if (turn) this.lifetimeTimer = setTimeout(() => this.fail(), MAX_TURN_LIFETIME_MS);
    const media = this.media!;
    this.url = URL.createObjectURL(media);
    media.addEventListener("sourceopen", () => {
      if (this.disposed || this.buffer) return;
      try {
        this.buffer = media.addSourceBuffer("audio/mpeg");
        this.buffer.addEventListener("updateend", () => this.drain());
        this.buffer.addEventListener("error", () => this.fail());
        this.drain();
      } catch { this.fail(); }
    });
    media.addEventListener("sourceclose", () => { if (!this.complete) this.fail(); });
    this.touch();
  }

  accept(event: AssistantSpeechAudioEvent): void {
    if (this.disposed || this.failed) return;
    if (this.providerEnded || event.phase === "error") { this.fail(); return; }
    if (event.phase === "start") { if (event.chunk_index !== 0 || this.nextIndex !== 0) this.fail(); return; }
    if (event.chunk_index !== this.nextIndex) { this.fail(); return; }
    if (event.phase === "alignment") return;
    if (event.phase === "end") {
      this.providerEnded = true;
      if (!this.nextIndex) { this.fail(); return; }
      // A future clause cannot open its MediaSource until the shared Audio
      // element reaches it. All transport bytes are present now, so playback
      // queue time must not be mistaken for an idle provider connection.
      clearTimeout(this.timer);
      this.drain();
      return;
    }
    try {
      const encoded = event.audio_data!;
      if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
        this.fail(); return;
      }
      const raw = atob(encoded);
      if (!raw.length || raw.length > MAX_SPEECH_STREAM_CHUNK_BYTES
        || this.pendingBytes + raw.length > MAX_SPEECH_STREAM_PENDING_BYTES
        || this.totalBytes + raw.length > (this.turn ? MAX_TURN_STREAM_BYTES : MAX_SPEECH_STREAM_BYTES)
        || AssistantSpeechStream.retainedBytes + raw.length > MAX_SPEECH_STREAM_RETAINED_BYTES) { this.fail(); return; }
      this.chunks.push(Uint8Array.from(raw, (character) => character.charCodeAt(0)));
      this.pendingBytes += raw.length;
      this.totalBytes += raw.length;
      AssistantSpeechStream.retainedBytes += raw.length;
      this.nextIndex += 1;
      this.touch();
      this.drain();
    } catch { this.fail(); }
  }

  fail(): void {
    if (this.disposed || this.failed) return;
    this.failed = true;
    try { this.onFailure(); } finally { this.dispose(); }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    clearTimeout(this.timer);
    clearTimeout(this.lifetimeTimer);
    this.chunks = [];
    this.pendingBytes = 0;
    AssistantSpeechStream.retainedBytes -= this.totalBytes;
    this.totalBytes = 0;
    try { if (this.buffer?.updating) this.buffer.abort(); } catch { /* Already detached. */ }
    this.buffer = null;
    this.media = null;
    URL.revokeObjectURL(this.url);
  }

  private touch(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.fail(), STREAM_IDLE_MS);
  }

  private drain(): void {
    const media = this.media;
    if (this.disposed || !this.buffer || this.buffer.updating || media?.readyState !== "open") return;
    try {
      const chunk = this.chunks.shift();
      if (chunk) {
        this.pendingBytes -= chunk.length;
        this.buffer.appendBuffer(chunk);
      } else if (this.providerEnded) {
        media.endOfStream();
        this.complete = true;
        clearTimeout(this.timer);
      }
    } catch { this.fail(); }
  }
}
