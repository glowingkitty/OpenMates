import type { VoiceHeardBoundary } from '../types/chat';
import type { AssistantSpeechStreamSource } from './assistantSpeechStream';
// assistantSpeechQueue.ts
// Owns browser playback for one assistant response at a time.
// Accepts only ready/generating segment metadata from its caller.
// Keeps playback ordered as progressively available segments arrive.
// Does not generate audio, retain plaintext, call the network, or use stores.
// Exposes state and duration-based regions for a host UI to render.

export type AssistantSpeechSegmentStatus = "generating" | "ready" | "failed";

export type AssistantSpeechChapter =
  | { kind: "heading"; text: string }
  | { kind: "part"; number: number }
  | { kind: "semantic"; type: "code" | "table" | "structured" }
  | { kind: "passive"; type: "confirmation" | "using_apps" };

export interface AssistantSpeechSegment {
  id: string;
  kind?: string;
  sequence: number;
  status: AssistantSpeechSegmentStatus;
  durationMs: number;
  audioUrl?: string;
  playbackClass: "passive" | "replayable";
  chapter: AssistantSpeechChapter;
  waveform: number[];
}

export type AssistantSpeechQueueStatus =
  | "idle"
  | "waiting_for_segment"
  | "playing"
  | "paused"
  | "waiting_for_more"
  | "stopped"
  | "completed"
  | "blocked_by_autoplay"
  | "failed";

export interface AssistantSpeechQueueState {
  responseId: string | null;
  status: AssistantSpeechQueueStatus;
  activeSegmentId: string | null;
}

export interface AssistantSpeechWaveformRegion {
  segmentId: string;
  sequence: number;
  start: number;
  end: number;
  status: AssistantSpeechSegmentStatus;
  active: boolean;
  chapter: AssistantSpeechChapter;
  waveform: number[];
}

interface SpeechAudio {
  addEventListener(event: "ended" | "error" | "waiting" | "playing" | "timeupdate", listener: () => void): void;
  removeEventListener?(event: string, listener: () => void): void;
  pause(): void;
  play(): Promise<void>;
  src?: string;
  currentTime?: number;
  duration?: number;
  loop?: boolean;
  playbackRate?: number;
  preservesPitch?: boolean;
  webkitPreservesPitch?: boolean;
  load?(): void;
}

interface MediaSessionControls {
  setActionHandler(
    action: "previoustrack" | "nexttrack" | "play" | "pause",
    handler: (() => void) | null,
  ): void;
}

export interface AssistantSpeechQueueOptions {
  audioFactory?: (url: string) => SpeechAudio;
  mediaSession?: MediaSessionControls;
  onStateChange?: (state: AssistantSpeechQueueState) => void;
  onNeedSegment?: (segment: AssistantSpeechSegment) => void;
}

const DEFAULT_STATE: AssistantSpeechQueueState = {
  responseId: null,
  status: "idle",
  activeSegmentId: null,
};

export const ASSISTANT_SPEECH_PLAYBACK_RATE = 1.25;
export const ASSISTANT_SPEECH_PREFETCH_LEAD_SECONDS = 6;
const PENDING_CUE_URL = "/audio/assistant-speech-pending.wav";

const SILENT_AUDIO_DATA_URL = "data:audio/wav;base64,UklGRnQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YVAAAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==";

/** Coordinates ordered, local audio playback for a single response. */
export class AssistantSpeechQueue {
  private static activeQueue: AssistantSpeechQueue | null = null;

  private readonly audioFactory: (url: string) => SpeechAudio;
  private readonly segments = new Map<string, AssistantSpeechSegment>();
  // WebKit grants autoplay permission per media element. Keep one element for
  // the acknowledgement and every generated chapter, changing only its source.
  private playbackAudio: SpeechAudio | null = null;
  private playbackAudioUrl: string | null = null;
  private silentPrimeState: "idle" | "pending" | "ready" = "idle";
  private currentAudio: SpeechAudio | null = null;
  private pendingSegmentId: string | null = null;
  private readonly completedSegmentIds = new Set<string>();
  private readonly heardVoiceSequences = new Set<number>();
  private autoplayPending = true;
  private playGeneration = 0;
  private complete = false;
  private liveResponseFailed = false;
  private pendingCue: SpeechAudio | null = null;
  private explicitSelectionPending = false;
  private readonly requestedSegmentIds = new Set<string>();
  private readonly streams = new Map<string, {
    source: AssistantSpeechStreamSource;
    failed: boolean;
    ended: boolean;
    offset: number;
  }>();
  private audioSourceGeneration = 0;
  private detachAudioEvents: (() => void) | null = null;
  private readonly onStateChange?: (state: AssistantSpeechQueueState) => void;
  private readonly onNeedSegment?: (segment: AssistantSpeechSegment) => void;

  state: AssistantSpeechQueueState = { ...DEFAULT_STATE };

  constructor(options: AssistantSpeechQueueOptions = {}) {
    this.audioFactory = options.audioFactory ?? ((url) => new Audio(url));
    this.onStateChange = options.onStateChange;
    this.onNeedSegment = options.onNeedSegment;
    this.registerMediaSessionHandlers(
      options.mediaSession ?? this.browserMediaSession,
    );
  }

  /** Actual media completion and current source-audio time, never guessed words.
   * Waiting confirmations and manual/passive clips grant no prose coverage. */
  get playbackBoundary(): VoiceHeardBoundary | null {
    const responseId = this.state.responseId;
    if (!responseId || responseId.length > 128) return null;
    const retainedOffset = this.state.activeSegmentId ? this.streams.get(this.state.activeSegmentId)?.offset ?? 0 : 0;
    const active = (this.currentAudio || retainedOffset > 0) && this.activeSegment?.kind === 'voice_prose_clause'
      && this.activeSegment.playbackClass === 'replayable' ? this.activeSegment : null;
    const activeSequence = active && Number.isSafeInteger(active.sequence) && active.sequence >= 0 && active.sequence <= 65_535
      ? active.sequence : null;
    const completed = [...this.heardVoiceSequences].sort((a, b) => a - b);
    if (!completed.length && activeSequence === null) return null;
    const seconds = activeSequence !== null ? this.currentAudio?.currentTime ?? retainedOffset : 0;
    return { assistant_message_id: responseId, completed_sequences: completed,
      active_sequence: activeSequence,
      active_offset_ms: Number.isFinite(seconds) ? Math.min(3_600_000, Math.max(0, Math.floor(seconds * 1000))) : 0 };
  }

  get waveformRegions(): AssistantSpeechWaveformRegion[] {
    const active = this.activeSegment;
    const segments = this.presentationMode === "passive_clip" && active
      ? [active]
      : this.orderedSegments.filter((segment) => segment.playbackClass === "replayable");
    const totalDuration = segments.reduce(
      (total, segment) => total + Math.max(segment.durationMs, 0),
      0,
    );
    let elapsed = 0;

    return segments.map((segment, index) => {
      const start = totalDuration === 0 ? index / segments.length : elapsed / totalDuration;
      elapsed += Math.max(segment.durationMs, 0);
      const end =
        totalDuration === 0
          ? (index + 1) / segments.length
          : index === segments.length - 1
            ? 1
            : elapsed / totalDuration;

      return {
        segmentId: segment.id,
        sequence: segment.sequence,
        start,
        end,
        status: segment.status,
        active: segment.id === this.state.activeSegmentId,
        chapter: segment.chapter,
        waveform: segment.waveform,
      };
    });
  }

  get presentationMode(): "passive_clip" | "replayable_track_queue" {
    return this.activeSegment?.playbackClass === "passive"
      ? "passive_clip"
      : "replayable_track_queue";
  }

  get hasReplayableTracks(): boolean {
    return this.orderedSegments.some((segment) => segment.playbackClass === "replayable");
  }

  segmentById(segmentId: string): AssistantSpeechSegment | undefined {
    return this.segments.get(segmentId);
  }

  start(responseId: string, segments: AssistantSpeechSegment[]): void {
    if (AssistantSpeechQueue.activeQueue && AssistantSpeechQueue.activeQueue !== this) {
      AssistantSpeechQueue.activeQueue.stop();
    }
    this.stopCurrentAudio();
    this.disposeStreams();
    this.autoplayPending = true;
    this.complete = false;
    this.liveResponseFailed = false;
    this.segments.clear();
    this.completedSegmentIds.clear();
    this.heardVoiceSequences.clear();
    this.requestedSegmentIds.clear();
    this.explicitSelectionPending = false;
    this.pendingSegmentId = null;
    this.setState({ responseId, status: "waiting_for_segment", activeSegmentId: null });
    for (const segment of segments) {
      this.segments.set(segment.id, segment);
    }
    AssistantSpeechQueue.activeQueue = this;
    this.activateFirstSegment();
  }

  upsertSegment(segment: AssistantSpeechSegment): void {
    if (!this.state.responseId || this.state.status === "stopped" || this.liveResponseFailed) {
      return;
    }
    const previous = this.segments.get(segment.id);
    const stream = this.streams.get(segment.id);
    if (stream) {
      if (segment.status === "failed" && !stream.failed && !stream.ended) {
        stream.source.fail();
        return;
      }
      if (stream.failed) {
        segment = { ...segment, status: "failed", audioUrl: undefined };
      } else {
        segment = { ...segment, status: "ready", audioUrl: stream.ended ? undefined : stream.source.url };
      }
    }
    // Late queued acknowledgements must not erase already resolved ready audio.
    if (previous?.status === "ready" && segment.status === "generating" && !stream) return;
    if (previous?.status === "ready" && segment.status === "ready" && !segment.audioUrl) {
      segment = { ...segment, audioUrl: previous.audioUrl, waveform: previous.waveform };
    }
    this.segments.set(segment.id, segment);
    if (stream?.ended && this.completedSegmentIds.has(segment.id)) {
      this.onStateChange?.({ ...this.state });
      return;
    }
    // Delayed confirmations are optional: useful speech wins as soon as ready,
    // and a failed confirmation must never fail the canonical response track.
    const realReady = segment.sequence >= 0 && segment.playbackClass === "replayable" && segment.status === "ready";
    const lateWaiting = segment.sequence === -1 && segment.kind === "waiting_confirmation" && this.orderedSegments.some((item) => item.sequence >= 0 && item.status === "ready");
    const waitingFailed = segment.sequence === -1 && segment.kind === "waiting_confirmation" && segment.status === "failed";
    const skipped = this.orderedSegments.filter((item) => item.sequence === -1 && item.kind === "waiting_confirmation"
      && (realReady || waitingFailed || lateWaiting));
    for (const item of skipped) {
      this.completedSegmentIds.add(item.id);
      const skippedStream = this.streams.get(item.id);
      if (skippedStream) { skippedStream.ended = true; skippedStream.source.dispose(); }
    }
    if (skipped.some((item) => item.id === this.state.activeSegmentId || item.id === this.pendingSegmentId)) {
      this.stopCurrentAudio();
      this.pendingSegmentId = null;
      this.setState({ ...this.state, activeSegmentId: null, status: this.autoplayPending ? "waiting_for_segment" : "paused" });
      this.activateFirstSegment();
      return;
    }
    if (waitingFailed || lateWaiting) return;
    if (this.currentAudio && this.state.status === "playing" && this.activeSegment) {
      this.maybePrefetchNext(this.activeSegment, this.currentAudio);
    }
    if (previous?.status === "failed" && segment.status === "ready" && segment.id === this.state.activeSegmentId) {
      this.setState({ ...this.state, status: this.autoplayPending ? "waiting_for_segment" : "paused" });
    }
    if (segment.status === "failed" && (segment.id === this.state.activeSegmentId || segment.id === this.pendingSegmentId)) {
      this.stopCurrentAudio();
      this.setState({ ...this.state, activeSegmentId: segment.id, status: "failed" });
      return;
    }
    if (previous?.status === "failed" && segment.status === "generating" && segment.id === this.state.activeSegmentId) {
      this.setState({ ...this.state, status: "waiting_for_segment" });
    }
    if (this.state.status === "waiting_for_more") {
      const nextSegment = this.orderedSegments.find((candidate) => !this.completedSegmentIds.has(candidate.id));
      this.pendingSegmentId = nextSegment?.id ?? null;
      if (!nextSegment || nextSegment.id !== segment.id || segment.status !== "ready") {
        if (nextSegment && this.autoplayPending && nextSegment.status !== "failed") {
          this.needSegment(nextSegment);
          this.startPendingCue();
        }
        return;
      }
    }
    if (!this.state.activeSegmentId || this.completedSegmentIds.has(this.state.activeSegmentId)) {
      this.setState({ ...this.state, activeSegmentId: null, status: this.autoplayPending ? "waiting_for_segment" : "paused" });
      this.activateFirstSegment();
      return;
    }

    const activeSegment = this.activeSegment;
    if (
      this.state.status === "waiting_for_segment" &&
      (activeSegment?.id === segment.id || this.pendingSegmentId === segment.id) &&
      segment.status === "ready"
    ) {
      if (this.pendingSegmentId === segment.id) {
        this.pendingSegmentId = null;
        this.setState({ ...this.state, activeSegmentId: segment.id });
      }
      if (this.autoplayPending) void this.playActiveSegment();
    }
  }

  async play(): Promise<void> {
    await this.resume();
  }

  /** Attach only after status has established the segment's canonical ordering. */
  attachStream(segmentId: string, source: AssistantSpeechStreamSource): boolean {
    const segment = this.segments.get(segmentId);
    if (!segment || !["voice_prose_clause", "waiting_confirmation"].includes(segment.kind ?? "") || this.state.status === "stopped" || this.liveResponseFailed
      || this.completedSegmentIds.has(segmentId) || this.streams.has(segmentId)
      || (segment.status === "ready" && segment.audioUrl)) return false;
    this.streams.set(segmentId, { source, failed: false, ended: false, offset: 0 });
    this.upsertSegment({ ...segment, status: "ready", audioUrl: source.url });
    return true;
  }

  failStream(segmentId: string, source: AssistantSpeechStreamSource): void {
    const stream = this.streams.get(segmentId);
    const segment = this.segments.get(segmentId);
    if (!stream || stream.source !== source || stream.failed || stream.ended || !segment) return;
    stream.failed = true;
    const active = this.state.activeSegmentId === segmentId;
    if (active) {
      const seconds = this.currentAudio?.currentTime ?? stream.offset;
      stream.offset = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
      this.stopCurrentAudio();
    }
    source.dispose();
    this.upsertSegment({ ...segment, status: "failed", audioUrl: undefined });
  }

  disposeStreams(): void {
    for (const stream of this.streams.values()) stream.source.dispose();
    this.streams.clear();
  }

  invalidateSegment(segmentId: string): void {
    const stream = this.streams.get(segmentId);
    if (this.state.activeSegmentId === segmentId) this.stopCurrentAudio();
    stream?.source.dispose();
    this.streams.delete(segmentId);
    const segment = this.segments.get(segmentId);
    if (segment) this.segments.set(segmentId, { ...segment, status: "failed", audioUrl: undefined });
    if (this.state.activeSegmentId === segmentId) {
      this.setState({ ...this.state, status: "failed" });
    }
  }

  retireSegmentVersion(segmentId: string): void {
    const stream = this.streams.get(segmentId);
    const segment = this.segments.get(segmentId);
    if (this.state.activeSegmentId === segmentId) {
      this.stopCurrentAudio();
      this.setState({ ...this.state, status: this.autoplayPending ? "waiting_for_segment" : "paused" });
    }
    stream?.source.dispose();
    this.streams.delete(segmentId);
    this.completedSegmentIds.delete(segmentId);
    if (segment) {
      this.heardVoiceSequences.delete(segment.sequence);
      this.segments.set(segmentId, { ...segment, status: "generating", audioUrl: undefined });
    }
  }

  /** Preserve iOS Safari's user-activation grant while generated audio is pending. */
  primeForAutoplay(): void {
    // Priming must never resume or replace the queue's active/paused prose.
    if (this.currentAudio) return;
    let audio = this.playbackAudio;
    if (audio && this.playbackAudioUrl === SILENT_AUDIO_DATA_URL && this.silentPrimeState !== "idle") return;
    if (!audio) {
      audio = this.audioFactory(SILENT_AUDIO_DATA_URL);
      this.playbackAudio = audio;
    } else if (this.playbackAudioUrl !== SILENT_AUDIO_DATA_URL) {
      // A completed/stopped source can still be attached to the shared element.
      // Replace it with silence before granting playback in this gesture.
      audio.src = SILENT_AUDIO_DATA_URL;
      audio.load?.();
    }
    this.playbackAudioUrl = SILENT_AUDIO_DATA_URL;
    this.bindPlaybackAudioEvents(audio);
    this.silentPrimeState = "pending";
    const sourceGeneration = this.audioSourceGeneration;
    const settled = (state: "idle" | "ready") => {
      if (sourceGeneration === this.audioSourceGeneration) this.silentPrimeState = state;
    };
    // A rejected silent play must be retried on this same element by the next
    // actual gesture. A pending/successful prime needs no duplicate play call.
    try { void audio.play().then(() => settled("ready"), () => settled("idle")); }
    catch { settled("idle"); }
  }

  pause(): void {
    if (!["playing", "waiting_for_segment", "waiting_for_more"].includes(this.state.status)) {
      return;
    }
    this.autoplayPending = false;
    this.playGeneration += 1;
    this.currentAudio?.pause();
    this.stopPendingCue();
    this.setState({ ...this.state, status: "paused" });
  }

  async resume(): Promise<void> {
    if (!this.state.responseId || this.state.status === "stopped" || this.liveResponseFailed) {
      return;
    }
    this.autoplayPending = true;
    if (this.streams.size && this.orderedSegments.every((segment) => this.completedSegmentIds.has(segment.id))) {
      // Live call sources are consumed once and disposed. Replaying saved text
      // is a separate manual Speak request, never an implicit regeneration.
      this.setState({ ...this.state, status: "completed" });
      return;
    }
    if (this.state.status === "completed") {
      for (const segmentId of this.completedSegmentIds) {
        if (!this.streams.has(segmentId)) this.completedSegmentIds.delete(segmentId);
      }
      this.setState({ ...this.state, activeSegmentId: null, status: "waiting_for_segment" });
    }
    if (this.state.activeSegmentId && this.completedSegmentIds.has(this.state.activeSegmentId)) {
      this.setState({ ...this.state, activeSegmentId: null, status: "waiting_for_segment" });
    }
    if (!this.state.activeSegmentId) {
      this.activateFirstSegment();
      return;
    }
    await this.playActiveSegment(true);
  }

  markComplete(): void {
    if (this.liveResponseFailed) return;
    this.complete = true;
    if (this.state.status !== "stopped" && !this.currentAudio && this.orderedSegments.every((segment) => this.completedSegmentIds.has(segment.id))) {
      this.setState({ ...this.state, status: "completed" });
    }
  }

  /** Final server membership is authoritative even when queued events are late. */
  sealLiveSegments(members: AssistantSpeechSegment[], failed = false): void {
    if (failed) {
      this.failLiveResponse();
      for (const segment of members) {
        if (!this.completedSegmentIds.has(segment.id)) this.segments.set(segment.id, {
          ...this.segments.get(segment.id), ...segment, status: "failed", audioUrl: undefined,
        });
      }
      this.setState({ ...this.state, status: "failed" });
      return;
    }
    if (this.liveResponseFailed) return;
    const ids = new Set(members.map((segment) => segment.id));
    for (const segment of this.orderedSegments) {
      if (segment.kind !== "voice_prose_clause" || ids.has(segment.id)) continue;
      if (this.state.activeSegmentId === segment.id) {
        this.stopCurrentAudio();
        this.setState({ ...this.state, activeSegmentId: null, status: "waiting_for_segment" });
      }
      this.streams.get(segment.id)?.source.dispose();
      this.streams.delete(segment.id);
      this.segments.delete(segment.id);
      this.completedSegmentIds.delete(segment.id);
      this.heardVoiceSequences.delete(segment.sequence);
      this.requestedSegmentIds.delete(segment.id);
    }
    for (const segment of members) this.upsertSegment(segment);
    this.markComplete();
  }

  private failLiveResponse(): void {
    this.liveResponseFailed = true;
    this.autoplayPending = false;
    const activeId = this.state.activeSegmentId;
    const activeStream = activeId ? this.streams.get(activeId) : undefined;
    if (activeStream && this.currentAudio) {
      const seconds = this.currentAudio.currentTime ?? 0;
      activeStream.offset = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
    }
    this.stopCurrentAudio();
    for (const [id, stream] of this.streams) {
      if (!stream.ended) stream.failed = true;
      stream.source.dispose();
      const segment = this.segments.get(id);
      if (segment && !this.completedSegmentIds.has(id)) this.segments.set(id, { ...segment, status: "failed", audioUrl: undefined });
    }
    this.setState({ ...this.state, status: "failed" });
  }

  fail(): void {
    this.stopCurrentAudio();
    this.stopPendingCue();
    this.setState({ ...this.state, status: "failed" });
  }

  stop(): void {
    this.autoplayPending = false;
    this.stopCurrentAudio();
    this.disposeStreams();
    this.stopPendingCue();
    this.explicitSelectionPending = false;
    this.setState({ ...this.state, status: "stopped" });
    if (AssistantSpeechQueue.activeQueue === this) {
      AssistantSpeechQueue.activeQueue = null;
    }
  }

  async previous(): Promise<void> {
    await this.moveBy(-1);
  }

  async next(): Promise<void> {
    await this.moveBy(1);
  }

  async selectSegment(segmentId: string): Promise<void> {
    if (this.liveResponseFailed) return;
    const segment = this.segments.get(segmentId);
    if (!segment) {
      return;
    }
    if (this.streams.get(segmentId)?.ended) {
      if (this.orderedSegments.every((item) => this.completedSegmentIds.has(item.id))) {
        this.setState({ ...this.state, status: "completed" });
      }
      return;
    }
    this.stopCurrentAudio();
    this.pendingSegmentId = null;
    this.explicitSelectionPending = true;
    this.completedSegmentIds.delete(segment.id);
    this.setState({ ...this.state, activeSegmentId: segment.id,
      status: segment.status === "failed" ? "failed" : this.autoplayPending ? "waiting_for_segment" : "paused",
    });
    if (segment.status === "ready") {
      if (this.autoplayPending) await this.playActiveSegment();
    } else if (segment.status !== "failed" && this.autoplayPending) {
      this.needSegment(segment);
      this.startPendingCue();
    }
  }

  async continueAfterUserGesture(): Promise<void> {
    if (this.state.status === "blocked_by_autoplay") {
      await this.playActiveSegment(true);
    }
  }

  private get orderedSegments(): AssistantSpeechSegment[] {
    return Array.from(this.segments.values()).sort(
      (left, right) => left.sequence - right.sequence || left.id.localeCompare(right.id),
    );
  }

  private get activeSegment(): AssistantSpeechSegment | undefined {
    return this.state.activeSegmentId
      ? this.segments.get(this.state.activeSegmentId)
      : undefined;
  }

  private get browserMediaSession(): MediaSessionControls | undefined {
    if (typeof navigator === "undefined" || !navigator.mediaSession) {
      return undefined;
    }
    return navigator.mediaSession;
  }

  private activateFirstSegment(): void {
    const firstSegment = this.orderedSegments.find((segment) => !this.completedSegmentIds.has(segment.id));
    if (!firstSegment) {
      return;
    }
    if (
      firstSegment.playbackClass === "replayable" &&
      firstSegment.sequence > 0 &&
      !this.orderedSegments.some((segment) => segment.sequence === 0)
    ) {
      return;
    }
    if (firstSegment.kind === "voice_prose_clause" && firstSegment.sequence > 0
      && !this.orderedSegments.some((segment) => segment.kind === "voice_prose_clause"
        && segment.sequence === firstSegment.sequence - 1 && this.completedSegmentIds.has(segment.id))) return;
    this.setState({ ...this.state, activeSegmentId: firstSegment.id });
    if (firstSegment.status === "failed") {
      this.setState({ ...this.state, status: "failed" });
    } else if (firstSegment.status === "ready" && this.autoplayPending) {
      void this.playActiveSegment();
    } else if (this.autoplayPending) {
      this.needSegment(firstSegment);
      this.startPendingCue();
    }
  }

  private async moveBy(direction: -1 | 1): Promise<void> {
    const segments = this.orderedSegments.filter((segment) => segment.playbackClass === "replayable");
    const activeIndex = segments.findIndex((segment) => segment.id === this.state.activeSegmentId);
    const targetIndex = activeIndex === -1 ? 0 : activeIndex + direction;
    const targetSegment = segments[targetIndex];
    if (!targetSegment) {
      return;
    }
    await this.selectSegment(targetSegment.id);
  }

  private async playActiveSegment(explicitResume = false): Promise<void> {
    const segment = this.activeSegment;
    if (segment?.status === "failed") {
      this.setState({ ...this.state, status: "failed" });
      return;
    }
    if (!segment || segment.status !== "ready" || !segment.audioUrl) {
      this.setState({ ...this.state, status: "waiting_for_segment" });
      if (segment && this.autoplayPending) {
        if (!this.streams.get(segment.id)?.failed) this.needSegment(segment);
        this.startPendingCue();
      }
      return;
    }
    // Native buffering leaves the same source playing (or its play promise
    // pending). Status/seal updates must not start it again, including when the
    // element was paused directly. Only an explicit Play resumes that source.
    if (!explicitResume && this.currentAudio === this.playbackAudio
      && this.playbackAudioUrl === segment.audioUrl) return;
    this.stopPendingCue();
    this.explicitSelectionPending = false;
    const audio = this.getAudio(segment);
    this.currentAudio = audio;

    const generation = ++this.playGeneration;
    try {
      await audio.play();
      if (generation !== this.playGeneration || !this.isCurrentAudio(segment.id, audio)) {
        return;
      }
      this.setState({ ...this.state, status: "playing" });
      this.maybePrefetchNext(segment, audio);
    } catch (error) {
      if (generation !== this.playGeneration || !this.isCurrentAudio(segment.id, audio)) {
        return;
      }
      if (this.isAutoplayBlocked(error)) {
        this.setState({ ...this.state, status: "blocked_by_autoplay" });
        return;
      }
      console.error("[AssistantSpeechQueue] Audio playback failed:", error);
      const stream = this.streams.get(segment.id);
      if (stream && !stream.failed && !stream.ended) { stream.source.fail(); return; }
      this.setState({ ...this.state, status: "failed" });
    }
  }

  private getAudio(segment: AssistantSpeechSegment): SpeechAudio {
    let audio = this.playbackAudio;
    if (!audio) {
      audio = this.audioFactory(segment.audioUrl!);
      this.playbackAudio = audio;
      this.playbackAudioUrl = segment.audioUrl!;
    } else if (this.playbackAudioUrl !== segment.audioUrl) {
      audio.src = segment.audioUrl!;
      this.playbackAudioUrl = segment.audioUrl!;
      audio.load?.();
    }
    audio.playbackRate = ASSISTANT_SPEECH_PLAYBACK_RATE;
    audio.preservesPitch = true;
    audio.webkitPreservesPitch = true;
    this.bindPlaybackAudioEvents(audio);
    return audio;
  }

  private bindPlaybackAudioEvents(audio: SpeechAudio): void {
    this.detachAudioEvents?.();
    const sourceGeneration = ++this.audioSourceGeneration;
    const listeners: { event: string; listener: () => void }[] = [];
    const listen = (event: Parameters<SpeechAudio["addEventListener"]>[0], callback: () => void) => {
      const listener = () => { if (sourceGeneration === this.audioSourceGeneration) callback(); };
      audio.addEventListener(event, listener);
      listeners.push({ event, listener });
    };
    this.detachAudioEvents = () => {
      for (const { event, listener } of listeners) audio.removeEventListener?.(event, listener);
    };
    listen("ended", () => {
      const segmentId = this.state.activeSegmentId;
      if (segmentId) this.handleSegmentEnded(segmentId, audio);
    });
    listen("error", () => {
      const segmentId = this.state.activeSegmentId;
      if (!segmentId || !this.isCurrentAudio(segmentId, audio)) return;
      const stream = this.streams.get(segmentId);
      if (stream && !stream.failed && !stream.ended) { stream.source.fail(); return; }
      console.error("[AssistantSpeechQueue] Audio element reported a playback error");
      this.stopCurrentAudio();
      this.setState({ ...this.state, status: "failed" });
    });
    listen("waiting", () => {
      const segmentId = this.state.activeSegmentId;
      if (segmentId && this.isCurrentAudio(segmentId, audio) && this.autoplayPending) {
        this.setState({ ...this.state, status: "waiting_for_segment" });
      }
    });
    listen("playing", () => {
      const segment = this.activeSegment;
      if (segment && this.isCurrentAudio(segment.id, audio) && this.autoplayPending) {
        this.setState({ ...this.state, status: "playing" });
        this.maybePrefetchNext(segment, audio);
      }
    });
    listen("timeupdate", () => {
      const segment = this.activeSegment;
      if (segment) this.maybePrefetchNext(segment, audio);
    });
  }

  private handleSegmentEnded(segmentId: string, audio: SpeechAudio): void {
    if (this.state.activeSegmentId !== segmentId || this.currentAudio !== audio) {
      return;
    }
    const stream = this.streams.get(segmentId);
    if (stream && !stream.failed && !stream.ended) {
      if (!stream.source.complete) { stream.source.fail(); return; }
      stream.ended = true;
      stream.source.dispose();
      const segment = this.segments.get(segmentId);
      if (segment) this.segments.set(segmentId, { ...segment,
        audioUrl: undefined, status: "ready" });
    }
    this.completedSegmentIds.add(segmentId);
    const ended = this.segments.get(segmentId);
    if (ended?.kind === 'voice_prose_clause' && ended.playbackClass === 'replayable'
      && Number.isSafeInteger(ended.sequence) && ended.sequence >= 0 && ended.sequence <= 65_535) {
      this.heardVoiceSequences.delete(ended.sequence);
      this.heardVoiceSequences.add(ended.sequence);
      if (this.heardVoiceSequences.size > 256) {
        const oldest = this.heardVoiceSequences.values().next().value;
        if (oldest !== undefined) this.heardVoiceSequences.delete(oldest);
      }
    }
    const segments = this.orderedSegments;
    const activeIndex = segments.findIndex((segment) => segment.id === segmentId);
    const nextSegment = segments[activeIndex + 1];
    this.currentAudio = null;
    if (ended?.kind === "voice_prose_clause" && nextSegment?.kind === "voice_prose_clause"
      && nextSegment.sequence !== ended.sequence + 1) {
      this.pendingSegmentId = null;
      this.setState({ ...this.state, status: "waiting_for_more" });
      return;
    }
    if (!nextSegment && this.complete) {
      this.setState({ ...this.state, status: "completed" });
      return;
    }
    if (nextSegment?.status === "failed") {
      this.setState({ ...this.state, activeSegmentId: nextSegment.id, status: "failed" });
      return;
    }
    if (!nextSegment || nextSegment.status !== "ready") {
      this.pendingSegmentId = nextSegment?.id ?? null;
      this.setState({ ...this.state, status: "waiting_for_more" });
      if (nextSegment && this.autoplayPending) {
        this.needSegment(nextSegment);
        this.startPendingCue();
      }
      return;
    }
    this.setState({
      ...this.state,
      activeSegmentId: nextSegment.id,
      status: "waiting_for_segment",
    });
    void this.playActiveSegment();
  }

  private stopCurrentAudio(): void {
    this.playGeneration += 1;
    this.stopPendingCue();
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
    if (this.playbackAudio && [...this.streams.values()].some((stream) => stream.source.url === this.playbackAudioUrl)) {
      // Detach MediaSource as well as revoking its URL so stopped calls release
      // the browser's coded-frame buffer while retaining the shared element.
      this.audioSourceGeneration += 1;
      this.detachAudioEvents?.();
      this.detachAudioEvents = null;
      this.playbackAudio.src = "";
      this.playbackAudioUrl = null;
      this.playbackAudio.load?.();
    }
  }

  private needSegment(segment: AssistantSpeechSegment): void {
    if (segment.status === "ready" || segment.status === "failed" || this.requestedSegmentIds.has(segment.id)) return;
    this.requestedSegmentIds.add(segment.id);
    this.onNeedSegment?.(segment);
  }

  private maybePrefetchNext(segment: AssistantSpeechSegment, audio: SpeechAudio): void {
    if (!this.isCurrentAudio(segment.id, audio) || this.state.status !== "playing") return;
    const duration = Number.isFinite(audio.duration) && (audio.duration ?? 0) > 0
      ? audio.duration! : segment.durationMs / 1000;
    const elapsed = Number.isFinite(audio.currentTime) ? audio.currentTime ?? 0 : 0;
    const remaining = Math.max(0, duration - elapsed) / ASSISTANT_SPEECH_PLAYBACK_RATE;
    if (remaining > ASSISTANT_SPEECH_PREFETCH_LEAD_SECONDS) return;
    const ordered = this.orderedSegments.filter((candidate) => candidate.playbackClass === "replayable");
    const next = ordered[ordered.findIndex((candidate) => candidate.id === segment.id) + 1];
    if (next) this.needSegment(next);
  }

  private startPendingCue(): void {
    if (this.pendingCue || !this.autoplayPending || this.state.status === "stopped" || !this.explicitSelectionPending) return;
    const cue = this.audioFactory(PENDING_CUE_URL);
    cue.loop = true;
    cue.playbackRate = 1;
    this.pendingCue = cue;
    void cue.play().catch(() => { if (this.pendingCue === cue) this.pendingCue = null; });
  }

  private stopPendingCue(): void {
    this.pendingCue?.pause();
    this.pendingCue = null;
  }

  private isAutoplayBlocked(error: unknown): boolean {
    return (
      typeof error === "object" &&
      error !== null &&
      "name" in error &&
      error.name === "NotAllowedError"
    );
  }

  private isCurrentAudio(segmentId: string, audio: SpeechAudio): boolean {
    return (
      this.state.activeSegmentId === segmentId &&
      this.currentAudio === audio &&
      this.state.status !== "stopped"
    );
  }

  private setState(state: AssistantSpeechQueueState): void {
    this.state = state;
    this.onStateChange?.({ ...state });
  }

  private registerMediaSessionHandlers(mediaSession?: MediaSessionControls): void {
    if (!mediaSession) {
      return;
    }
    mediaSession.setActionHandler("previoustrack", () => void this.previous());
    mediaSession.setActionHandler("nexttrack", () => void this.next());
    mediaSession.setActionHandler("play", () => void this.resume());
    mediaSession.setActionHandler("pause", () => this.pause());
  }
}
