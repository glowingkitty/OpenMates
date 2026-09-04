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
  addEventListener(event: "ended", listener: () => void): void;
  pause(): void;
  play(): Promise<void>;
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
}

interface CachedAudio {
  audio: SpeechAudio;
  url: string;
}

const DEFAULT_STATE: AssistantSpeechQueueState = {
  responseId: null,
  status: "idle",
  activeSegmentId: null,
};

/** Coordinates ordered, local audio playback for a single response. */
export class AssistantSpeechQueue {
  private static activeQueue: AssistantSpeechQueue | null = null;

  private readonly audioFactory: (url: string) => SpeechAudio;
  private readonly segments = new Map<string, AssistantSpeechSegment>();
  private readonly audioBySegmentId = new Map<string, CachedAudio>();
  private currentAudio: SpeechAudio | null = null;
  private pendingSegmentId: string | null = null;
  private readonly completedSegmentIds = new Set<string>();
  private autoplayPending = true;
  private readonly onStateChange?: (state: AssistantSpeechQueueState) => void;

  state: AssistantSpeechQueueState = { ...DEFAULT_STATE };

  constructor(options: AssistantSpeechQueueOptions = {}) {
    this.audioFactory = options.audioFactory ?? ((url) => new Audio(url));
    this.onStateChange = options.onStateChange;
    this.registerMediaSessionHandlers(
      options.mediaSession ?? this.browserMediaSession,
    );
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

  start(responseId: string, segments: AssistantSpeechSegment[]): void {
    if (AssistantSpeechQueue.activeQueue && AssistantSpeechQueue.activeQueue !== this) {
      AssistantSpeechQueue.activeQueue.stop();
    }
    this.stopCurrentAudio();
    this.autoplayPending = true;
    this.segments.clear();
    this.audioBySegmentId.clear();
    this.completedSegmentIds.clear();
    this.pendingSegmentId = null;
    this.setState({ responseId, status: "waiting_for_segment", activeSegmentId: null });
    for (const segment of segments) {
      this.segments.set(segment.id, segment);
    }
    AssistantSpeechQueue.activeQueue = this;
    this.activateFirstSegment();
  }

  upsertSegment(segment: AssistantSpeechSegment): void {
    if (!this.state.responseId || this.state.status === "stopped") {
      return;
    }
    this.segments.set(segment.id, segment);
    const cachedAudio = this.audioBySegmentId.get(segment.id);
    if (cachedAudio && cachedAudio.url !== segment.audioUrl) {
      cachedAudio.audio.pause();
      this.audioBySegmentId.delete(segment.id);
    }

    if (this.state.status === "waiting_for_more") {
      const nextSegment = this.orderedSegments.find((candidate) => !this.completedSegmentIds.has(candidate.id));
      this.pendingSegmentId = nextSegment?.id ?? null;
      if (!nextSegment || nextSegment.id !== segment.id || segment.status !== "ready") {
        return;
      }
    }
    if (!this.state.activeSegmentId || this.completedSegmentIds.has(this.state.activeSegmentId)) {
      this.setState({ ...this.state, activeSegmentId: null, status: "waiting_for_segment" });
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

  pause(): void {
    if (!["playing", "waiting_for_segment", "waiting_for_more"].includes(this.state.status)) {
      return;
    }
    this.autoplayPending = false;
    this.currentAudio?.pause();
    this.setState({ ...this.state, status: "paused" });
  }

  async resume(): Promise<void> {
    if (!this.state.responseId || this.state.status === "stopped") {
      return;
    }
    this.autoplayPending = true;
    if (!this.state.activeSegmentId) {
      this.activateFirstSegment();
      return;
    }
    await this.playActiveSegment();
  }

  stop(): void {
    this.autoplayPending = false;
    this.stopCurrentAudio();
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
    const segment = this.segments.get(segmentId);
    if (!segment) {
      return;
    }
    this.stopCurrentAudio();
    this.pendingSegmentId = null;
    this.autoplayPending = this.state.status !== "paused";
    this.setState({ ...this.state, activeSegmentId: segment.id, status: "waiting_for_segment" });
    if (segment.status === "ready") {
      if (this.autoplayPending) await this.playActiveSegment();
    }
  }

  async continueAfterUserGesture(): Promise<void> {
    if (this.state.status === "blocked_by_autoplay") {
      await this.playActiveSegment();
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
    this.setState({ ...this.state, activeSegmentId: firstSegment.id });
    if (firstSegment.status === "ready") {
      void this.playActiveSegment();
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

  private async playActiveSegment(): Promise<void> {
    const segment = this.activeSegment;
    if (!segment || segment.status !== "ready" || !segment.audioUrl) {
      this.setState({ ...this.state, status: "waiting_for_segment" });
      return;
    }
    const audio = this.getAudio(segment);
    this.currentAudio = audio;

    try {
      await audio.play();
      if (!this.isCurrentAudio(segment.id, audio)) {
        return;
      }
      this.setState({ ...this.state, status: "playing" });
    } catch (error) {
      if (!this.isCurrentAudio(segment.id, audio)) {
        return;
      }
      if (this.isAutoplayBlocked(error)) {
        this.setState({ ...this.state, status: "blocked_by_autoplay" });
        return;
      }
      console.error("[AssistantSpeechQueue] Audio playback failed:", error);
      this.setState({ ...this.state, status: "failed" });
    }
  }

  private getAudio(segment: AssistantSpeechSegment): SpeechAudio {
    const cached = this.audioBySegmentId.get(segment.id);
    if (cached && cached.url === segment.audioUrl) {
      return cached.audio;
    }
    const audio = this.audioFactory(segment.audioUrl!);
    audio.addEventListener("ended", () => this.handleSegmentEnded(segment.id, audio));
    this.audioBySegmentId.set(segment.id, { audio, url: segment.audioUrl! });
    return audio;
  }

  private handleSegmentEnded(segmentId: string, audio: SpeechAudio): void {
    if (this.state.activeSegmentId !== segmentId || this.currentAudio !== audio) {
      return;
    }
    this.completedSegmentIds.add(segmentId);
    const segments = this.orderedSegments;
    const activeIndex = segments.findIndex((segment) => segment.id === segmentId);
    const nextSegment = segments[activeIndex + 1];
    this.currentAudio = null;
    if (!nextSegment || nextSegment.status !== "ready") {
      this.pendingSegmentId = nextSegment?.id ?? null;
      this.setState({ ...this.state, status: "waiting_for_more" });
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
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
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
