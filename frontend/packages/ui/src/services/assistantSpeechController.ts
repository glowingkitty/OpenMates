// assistantSpeechController.ts
// Bridges assistant message text, owner-scoped WebSocket status, generated assets,
// and the browser-only AssistantSpeechQueue. Only transient projected text leaves
// this module; status handling and player state never expose persisted plaintext.
// One controller instance owns playback across the application.

import { get, writable, type Readable } from "svelte/store";
import {
  fetchAndDecryptAudio,
  releaseCachedAudio,
} from "../components/embeds/audio/audioEmbedCrypto";
import { decodeToonContent, resolveEmbed } from "./embedResolver";
import {
  AssistantSpeechQueue,
  type AssistantSpeechChapter,
  type AssistantSpeechQueueState,
  type AssistantSpeechSegment,
  type AssistantSpeechWaveformRegion,
} from "./assistantSpeechQueue";
import { buildWaveformFromAudioUrl } from "../utils/audioWaveform";
import { webSocketService } from "./websocketService";
import { locale } from "svelte-i18n";
import { projectAssistantSpeech as projectSharedAssistantSpeech } from "../../../assistantSpeechProjection";
import {
  AssistantSpeechStream,
  isAssistantSpeechAudioEvent,
  supportsAssistantSpeechStream,
  type AssistantSpeechAudioEvent,
} from "./assistantSpeechStream";

interface ProjectedSpeechSegment {
  sequence: number;
  kind: string;
  speakable_text: string;
  source_version: number;
  source_hash: string;
  chapter: AssistantSpeechChapter;
}

interface SpeechStatusSegment {
  segment_id?: string;
  status?: "accepted" | "registered" | "queued" | "generating" | "ready" | "error" | "cancelled" | "deleted" | "invalidated" | "sealed";
  generated_asset_id?: string;
  duration_seconds?: number;
  retryable?: boolean;
  sequence?: number;
  request_sequence?: number;
  kind?: string;
  source_version?: number;
  execution_version?: number;
}

interface SpeechStatusPayload extends SpeechStatusSegment {
  voice_call_id?: string;
  chat_id?: string;
  message_id?: string;
  segments?: SpeechStatusSegment[];
  turn_track_id?: string;
  error?: string;
}

interface SpeechAcknowledgementPayload {
  chat_id?: string;
  message_id?: string;
  clip_id?: string;
  audio_url?: string;
}

export interface AssistantSpeechPlayerState extends AssistantSpeechQueueState {
  chatId: string | null;
  messageId: string | null;
  regions: AssistantSpeechWaveformRegion[];
  error: string | null;
  presentationMode: "passive_clip" | "replayable_track_queue";
  hasReplayableTracks: boolean;
  mateName: string;
  mateCategory: string;
}

export interface PublicAssistantSpeechSegment {
  segment_id: string;
  sequence: number;
  public_url: string;
  duration_seconds: number;
}

export interface AssistantSpeechPlaybackController {
  player: Readable<AssistantSpeechPlayerState>;
  pause(): void;
  play(): Promise<void>;
  previous(): Promise<void>;
  next(): Promise<void>;
  selectSegment(segmentId: string): Promise<void>;
  continueAfterUserGesture(): Promise<void>;
  close(): Promise<void>;
}

const INITIAL_PLAYER_STATE: AssistantSpeechPlayerState = {
  responseId: null,
  chatId: null,
  messageId: null,
  status: "idle",
  activeSegmentId: null,
  regions: [],
  error: null,
  presentationMode: "replayable_track_queue",
  hasReplayableTracks: false,
  mateName: "OpenMates",
  mateCategory: "default",
};
const GENERATED_ASSET_RETRY_MS = 150;
const GENERATED_ASSET_RETRY_COUNT = 20;
const MAX_STOPPED_MESSAGE_IDS = 50;
const MAX_EARLY_AUDIO_BYTES = 512 * 1024;
const MAX_EARLY_AUDIO_SEGMENTS = 8;
// Bound pending identities as well as the stream helper's global 16 MiB byte
// budget. Each unopened clause has a separate 512 KiB pending-byte limit.
const MAX_LIVE_AUDIO_STREAMS = 32;
const MAX_AUDIO_ATTEMPTS = 256;
const EARLY_AUDIO_TIMEOUT_MS = 15_000;
const LIVE_SEAL_ERROR = "Speech is temporarily unavailable.";

class AssistantSpeechController {
  readonly player = writable<AssistantSpeechPlayerState>(INITIAL_PLAYER_STATE);
  readonly activity = writable({ chatId: null as string | null, messageId: null as string | null,
    text: "", speaking: false, language: "en" });
  private callOwner: string | null = null;
  private activeCallId: string | null = null;
  private canonicalSource: { chatId: string; messageId: string; text: string } | null = null;
  private readonly queue = new AssistantSpeechQueue({
    onStateChange: () => this.publish(),
    onNeedSegment: (segment) => { void this.requestGeneration(segment); },
  });
  private pending: {
    chatId: string;
    messageId: string;
    projected: ProjectedSpeechSegment[];
  } | null = null;
  private segmentSequence = new Map<string, number>();
  private readonly latestStatusBySegmentId = new Map<string, SpeechStatusSegment>();
  private lastRequest: { chatId: string; messageId: string; projected: ProjectedSpeechSegment[] } | null = null;
  private source: { chatId: string; messageId: string; projected: ProjectedSpeechSegment[] } | null = null;
  private readonly generationRequestedIds = new Set<string>();
  private readonly waitingForSource = new Map<string, AssistantSpeechSegment>();
  private streamPreludeOffset = 0;
  private readonly liveAudio = new Map<string, AssistantSpeechStream>();
  private readonly audioAttempts = new Map<string, AssistantSpeechAudioEvent>();
  private readonly liveCallSegmentIds = new Set<string>();
  private readonly rejectedLiveAudio = new Set<string>();
  private turnTrack: { id: string; messageId: string; sourceVersion: number; executionVersion: number } | null = null;
  private liveSeal: {
    chatId: string; messageId: string; callId: string; sourceVersion: number;
    members: Map<string, number>;
    trackId?: string;
    failed: boolean;
  } | null = null;
  private readonly earlyAudio = new Map<string, {
    events: AssistantSpeechAudioEvent[];
    bytes: number;
    timer: ReturnType<typeof setTimeout>;
  }>();
  private earlyAudioBytes = 0;
  private chatId: string | null = null;
  private messageId: string | null = null;
  private error: string | null = null;
  private readonly stoppedMessageIds = new Set<string>();
  private readonly dismissedMessageIds = new Set<string>();
  private readonly audioKeyBySegmentId = new Map<string, string>();
  private readonly audioResolutionBySegmentId = new Map<string, {
    generation: number;
    assetId: string;
    promise: Promise<{ url: string; s3Key: string | null }>;
  }>();
  private audioResolutionGeneration = 0;
  private publicPlayback = false;
  private mateName = "OpenMates";
  private mateCategory = "default";
  private readonly presentationBySegmentId = new Map<string, {
    chapter: AssistantSpeechChapter;
    kind: string;
    playbackClass: "passive" | "replayable";
  }>();

  constructor() {
    // Asset publication and speech readiness travel independently. Subscribe to
    // the existing post-storage event so delayed client encryption can recover.
    void import("./chatSyncService").then(({ chatSyncService }) => {
      chatSyncService.addEventListener("embedUpdated", (event: Event) => {
        const assetId = (event as CustomEvent<{ embed_id?: string }>).detail?.embed_id;
        if (!assetId || this.queue.state.status === "stopped") return;
        for (const status of Array.from(this.latestStatusBySegmentId.values())) {
          if (status.status === "ready" && status.generated_asset_id === assetId) {
            void this.hydrateReadySegment(status);
          }
        }
      });
    }).catch((cause) => console.error("[AssistantSpeechController] Asset recovery subscription failed:", cause));
    webSocketService.on<SpeechStatusPayload>("assistant_speech_status", (payload) => {
      void this.handleStatus(payload);
    });
    webSocketService.on<SpeechAcknowledgementPayload>("assistant_speech_acknowledgement", (payload) => {
      this.handleAcknowledgement(payload);
    });
    webSocketService.on<unknown>("assistant_speech_audio", (payload) => this.handleAudio(payload));
  }

  async request(
    chatId: string,
    messageId: string,
    markdown: string,
    mate: { name?: string; category?: string } = {},
  ): Promise<void> {
    if (this.callOwner) return;
    const projected = projectAssistantSpeech(markdown);
    if (projected.length === 0) return;
    if (this.liveCallSegmentIds.size) {
      this.queue.stop();
      this.releaseGeneratedAudio();
      this.segmentSequence.clear();
      this.presentationBySegmentId.clear();
      this.latestStatusBySegmentId.clear();
    }
    this.supersedeCurrentMessage(messageId);
    this.pending = { chatId, messageId, projected };
    this.lastRequest = this.pending;
    this.source = this.pending;
    this.canonicalSource = { chatId, messageId, text: markdown };
    this.generationRequestedIds.clear();
    this.waitingForSource.clear();
    this.stoppedMessageIds.delete(messageId);
    this.dismissedMessageIds.delete(messageId);
    this.chatId = chatId;
    this.messageId = messageId;
    this.error = null;
    for (const [id, status] of this.latestStatusBySegmentId) {
      if (status.status === "error") this.latestStatusBySegmentId.delete(id);
    }
    this.publicPlayback = false;
    this.mateName = mate.name || "OpenMates";
    this.mateCategory = mate.category || "default";
    if (this.queue.state.responseId !== messageId || this.queue.state.status === "stopped") {
      this.queue.start(messageId, []);
    }
    this.publish();
    await this.sendRequest();
  }

  pause(): void { this.queue.pause(); }
  /** A call keeps the one shared player scoped to its ordinary chat. */
  setCallOwner(chatId: string | null, callId?: string | null): void {
    if (this.activeCallId && (!chatId || chatId !== this.callOwner || (callId !== undefined && callId !== this.activeCallId))) {
      this.queue.stop();
      this.disposeLiveAudio();
    }
    if (!chatId || chatId !== this.callOwner) this.activeCallId = null;
    if (callId !== undefined) this.activeCallId = callId;
    this.callOwner = chatId;
    if (!chatId) this.canonicalSource = null;
    if (chatId && this.chatId && this.chatId !== chatId) void this.stop();
    this.publish();
  }
  get playbackBoundary() { return this.queue.playbackBoundary; }
  getCurrentSourceText(messageId?: string): string {
    return (!messageId || this.canonicalSource?.messageId === messageId)
      ? this.canonicalSource?.text ?? "" : "";
  }
  /** Hold only the current owner's decrypted stream text until a chapter is needed. */
  registerSource(chatId: string, messageId: string, markdown: string): void {
    if (this.callOwner && chatId !== this.callOwner) return;
    if (!markdown || this.publicPlayback || this.stoppedMessageIds.has(messageId)) return;
    this.canonicalSource = { chatId, messageId, text: markdown };
    this.source = { chatId, messageId, projected: projectAssistantSpeech(markdown) };
    for (const segment of this.waitingForSource.values()) void this.requestGeneration(segment);
    this.publish();
  }
  primeForAutoplay(): void { this.queue.primeForAutoplay(); }
  async play(): Promise<void> {
    if (this.queue.state.status === "failed") {
      const activeId = this.queue.state.activeSegmentId;
      const ready = activeId ? this.latestStatusBySegmentId.get(activeId) : undefined;
      this.error = null;
      if (ready?.status === "ready") {
        await this.hydrateReadySegment(ready);
      } else if (this.lastRequest) {
        if (ready) {
          await this.hydrateReadySegment({ ...ready, status: "queued" });
        } else if (!activeId) {
          this.queue.start(this.lastRequest.messageId, []);
        }
        if (activeId) {
          this.generationRequestedIds.delete(activeId);
          const segment = this.queue.segmentById(activeId);
          if (segment) await this.requestGeneration(segment);
        } else {
          this.pending = this.lastRequest;
          await this.sendRequest();
        }
        if (this.error) return;
      }
    }
    await this.queue.play();
  }

  private async sendRequest(): Promise<void> {
    const request = this.pending;
    if (!request) return;
    try {
      await webSocketService.sendMessage("assistant_speech", {
        action: "request", chat_id: request.chatId, assistant_message_id: request.messageId,
        defer_after_first: true,
        source_markdown: this.canonicalSource?.messageId === request.messageId ? this.canonicalSource.text : undefined,
        segments: request.projected.map(({ chapter: _chapter, ...segment }) => segment),
      });
    } catch (cause) {
      if (this.messageId !== request.messageId) return;
      console.error("[AssistantSpeechController] Speech request failed:", cause);
      this.error = "Speech is temporarily unavailable.";
      this.queue.fail();
    }
  }
  private async requestGeneration(segment: AssistantSpeechSegment): Promise<void> {
    // Live calls are server-push only. Missing transport bytes must not turn
    // queue demand into a second, stored manual speech generation.
    if (this.callOwner) return;
    if (this.publicPlayback || !this.chatId || !this.messageId || segment.status === "ready" || this.generationRequestedIds.has(segment.id)) return;
    const source = this.source;
    const requestSequence = this.lastRequest?.messageId === this.messageId
      ? segment.sequence : segment.sequence - this.streamPreludeOffset;
    const projected = source?.chatId === this.chatId && source.messageId === this.messageId
      ? source.projected.find((candidate) => candidate.sequence === requestSequence) : undefined;
    const voiceClause = this.latestStatusBySegmentId.get(segment.id)?.kind === "voice_prose_clause";
    const rawSource = this.canonicalSource?.messageId === this.messageId ? this.canonicalSource.text : undefined;
    if (!projected && !(voiceClause && rawSource)) {
      this.waitingForSource.set(segment.id, segment);
      return;
    }
    this.waitingForSource.delete(segment.id);
    this.generationRequestedIds.add(segment.id);
    // A user retry starts a fresh attempt; stale queue events cannot reset a failure.
    if (this.latestStatusBySegmentId.get(segment.id)?.status === "error") {
      this.latestStatusBySegmentId.delete(segment.id);
    }
    try {
      const { chapter: _chapter, ...requestSegment } = projected ?? {
        chapter: defaultPresentation(segment.sequence).chapter, sequence: segment.sequence,
        source_version: 1, source_hash: "server-verified", kind: "voice_prose_clause", speakable_text: "canonical voice clause",
      };
      await webSocketService.sendMessage("assistant_speech", {
        action: "generate", chat_id: this.chatId, assistant_message_id: this.messageId,
        source_markdown: rawSource,
        segments: [{ ...requestSegment, ...(voiceClause ? {segment_id: segment.id, kind: "voice_prose_clause"} : {}) }],
      });
    } catch (cause) {
      this.generationRequestedIds.delete(segment.id);
      console.error("[AssistantSpeechController] Speech chapter request failed:", cause);
      if (this.queue.state.activeSegmentId === segment.id) {
        this.error = "Speech is temporarily unavailable.";
        this.queue.fail();
      }
    }
  }
  previous(): Promise<void> { return this.queue.previous(); }
  next(): Promise<void> { return this.queue.next(); }
  selectSegment(segmentId: string): Promise<void> { return this.queue.selectSegment(segmentId); }
  continueAfterUserGesture(): Promise<void> { return this.queue.continueAfterUserGesture(); }

  async close(): Promise<void> {
    this.canonicalSource = null;
    if (this.messageId) this.dismissedMessageIds.add(this.messageId);
    this.audioResolutionGeneration += 1;
    this.queue.stop();
    this.lastRequest = null;
    this.pending = null;
    this.releaseGeneratedAudio();
    this.source = null;
    this.waitingForSource.clear();
    if (!this.publicPlayback && this.chatId && this.messageId) {
      try {
        await webSocketService.sendMessage("assistant_speech", { action: "cancel", chat_id: this.chatId, assistant_message_id: this.messageId });
      } catch (cause) {
        console.error("[AssistantSpeechController] Speech cancellation failed:", cause);
      }
    }
  }

  async playPublicExample(chatId: string, messageId: string, fixtures: PublicAssistantSpeechSegment[]): Promise<void> {
    if (this.callOwner) return;
    if (fixtures.length === 0) return;
    await this.stop();
    this.pending = null;
    this.stoppedMessageIds.delete(messageId);
    this.dismissedMessageIds.delete(messageId);
    this.chatId = chatId;
    this.messageId = messageId;
    this.error = null;
    this.publicPlayback = true;
    this.queue.start(messageId, fixtures.map((fixture) => {
      const presentation = defaultPresentation(fixture.sequence, "prose_paragraph");
      this.presentationBySegmentId.set(fixture.segment_id, presentation);
      return {
        id: fixture.segment_id,
        sequence: fixture.sequence,
        status: "ready",
        durationMs: Math.max(0, fixture.duration_seconds * 1000),
        audioUrl: fixture.public_url,
        waveform: [],
        ...presentation,
      };
    }));
    this.queue.markComplete();
    this.publish();
  }

  async stop(): Promise<void> {
    this.canonicalSource = null;
    if (this.messageId) this.rememberStoppedMessage(this.messageId);
    this.audioResolutionGeneration += 1;
    this.queue.stop();
    this.releaseGeneratedAudio();
    this.source = null;
    this.waitingForSource.clear();
    const shouldCancel = !this.publicPlayback;
    this.publicPlayback = false;
    if (shouldCancel && this.chatId && this.messageId) {
      await webSocketService.sendMessage("assistant_speech", {
        action: "cancel",
        chat_id: this.chatId,
        assistant_message_id: this.messageId,
      });
    }
  }

  private async handleStatus(payload: SpeechStatusPayload): Promise<void> {
    if (payload.voice_call_id && (!this.callOwner || payload.voice_call_id !== this.activeCallId)) return;
    if (this.callOwner && payload.chat_id !== this.callOwner) return;
    const statusMessageId = payload.message_id ?? this.pending?.messageId;
    if (statusMessageId && (this.stoppedMessageIds.has(statusMessageId) || this.dismissedMessageIds.has(statusMessageId))) {
      if (payload.chat_id && ["accepted", "queued"].includes(payload.status ?? "")) {
        void webSocketService.sendMessage("assistant_speech", {
          action: "cancel", chat_id: payload.chat_id, assistant_message_id: statusMessageId,
        }).catch((cause) => console.error("[AssistantSpeechController] Late speech cancellation failed:", cause));
      }
      return;
    }
    if (payload.status === "sealed") { this.handleLiveSeal(payload); return; }
    if (payload.kind === "voice_prose_turn" && payload.voice_call_id) {
      await this.handleTurnStatus(payload); return;
    }
    if (this.turnTrack?.messageId === payload.message_id && payload.kind === "voice_prose_clause") {
      if (payload.segment_id && Number.isSafeInteger(payload.sequence) && payload.sequence! >= 0
        && payload.source_version === this.turnTrack.sourceVersion) {
        this.latestStatusBySegmentId.set(payload.segment_id, payload);
        this.segmentSequence.set(payload.segment_id, payload.sequence!);
        this.queue.registerTurnClause(payload.segment_id, payload.sequence!);
        if (payload.status === "error" || this.isCancelledStatus(payload)) this.queue.fail();
      }
      this.publish(); return;
    }
    if (!this.matchesLiveSeal(payload)) return;
    if (payload.message_id) this.supersedeCurrentMessage(payload.message_id);
    if (payload.status === "accepted" && payload.segments && this.pending) {
      const { chatId, messageId, projected } = this.pending;
      this.pending = null;
      this.chatId = chatId;
      this.messageId = messageId;
      this.segmentSequence.clear();
      // Cached rows and newly queued rows are returned in separate groups.
      // Join chapter metadata by sequence, never by acceptance array position.
      const sequences = payload.segments.flatMap((status) => typeof status.sequence === "number" ? [status.sequence] : []);
      const sequenceOffset = sequences.length ? Math.max(0, Math.min(...sequences) - projected[0].sequence) : 0;
      const segments = payload.segments.flatMap((status, index) => {
        const sequence = status.request_sequence ?? ((status.sequence ?? projected[index]?.sequence ?? index) - sequenceOffset);
        const source = projected.find((segment) => segment.sequence === sequence);
        if (!status.segment_id || (!source && status.kind !== "voice_prose_clause")) return [];
        if (payload.voice_call_id) this.liveCallSegmentIds.add(status.segment_id);
        const latest = this.latestStatusBySegmentId.get(status.segment_id);
        if (this.isCancelledStatus(latest)) return [];
        if ((latest?.status === "ready" || latest?.status === "error") && !this.olderAudioVersion(latest, status)) status = { ...status, ...latest };
        this.latestStatusBySegmentId.set(status.segment_id, status);
        this.segmentSequence.set(status.segment_id, sequence);
        const presentation = {
          chapter: status.kind === "voice_prose_clause" ? defaultPresentation(sequence).chapter : source!.chapter,
          kind: status.kind || source!.kind,
          playbackClass: status.kind === "app_use_announcement" ? "passive" as const : "replayable" as const,
        };
        this.presentationBySegmentId.set(status.segment_id, presentation);
        return [{
          id: status.segment_id,
          sequence,
          status: status.status === "ready" ? "ready" : status.status === "error" ? "failed" : "generating",
          durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
          waveform: [],
          ...presentation,
        } satisfies AssistantSpeechSegment];
      });
      for (const status of payload.segments) {
        if (status.segment_id && status.status !== "registered") this.generationRequestedIds.add(status.segment_id);
      }
      if (this.queue.state.responseId === messageId && this.queue.state.status !== "stopped") {
        for (const segment of segments) this.queue.upsertSegment(segment);
      } else {
        this.queue.start(messageId, segments);
      }
      this.queue.markComplete();
      for (const status of payload.segments) if (status.segment_id) this.flushEarlyAudio(status.segment_id);
      await Promise.all(payload.segments.map((status) => this.hydrateReadySegment(this.latestStatusBySegmentId.get(status.segment_id ?? "") ?? status)));
      return;
    }

    if (payload.status === "accepted" && payload.segments) {
      await Promise.all(payload.segments.map((status) => this.handleStatus({ ...status,
        chat_id: payload.chat_id ?? this.chatId ?? undefined, message_id: payload.message_id ?? this.messageId ?? undefined,
        voice_call_id: payload.voice_call_id })));
      return;
    }

    if (payload.status === "error" && !payload.segment_id) {
      this.error = "Speech is temporarily unavailable.";
      this.queue.fail();
      this.publish();
      return;
    }
    if (payload.segment_id) {
      const latest = this.latestStatusBySegmentId.get(payload.segment_id);
      if (this.isCancelledStatus(latest)) return;
      const attempt = this.audioAttempts.get(payload.segment_id);
      if (this.olderAudioVersion(payload, latest ?? {}) || (attempt && this.olderAudioVersion(payload, attempt))) return;
      if (this.isCancelledStatus(payload)) {
        this.latestStatusBySegmentId.set(payload.segment_id, payload);
        this.dropEarlyAudio(payload.segment_id);
        this.liveAudio.get(payload.segment_id)?.dispose();
        this.liveAudio.delete(payload.segment_id);
        this.queue.invalidateSegment(payload.segment_id);
        return;
      }
      if ((latest?.status === "ready" || latest?.status === "error") && !this.olderAudioVersion(latest, payload)
        && ["registered", "queued", "generating"].includes(payload.status ?? "")) return;
      if (latest && this.olderAudioVersion(latest, payload)) this.retireAudioVersion(payload.segment_id);
      if (payload.voice_call_id) this.liveCallSegmentIds.add(payload.segment_id);
      this.latestStatusBySegmentId.set(payload.segment_id, payload);
      if (payload.status === "queued" || payload.status === "generating" || payload.status === "ready") {
        this.generationRequestedIds.add(payload.segment_id);
      }
      // Acceptance supplies authoritative ordering and chapter metadata for manual
      // requests. Retain early readiness rather than starting a partial queue.
      if (this.pending) return;
      if (
        typeof payload.sequence === "number" &&
        payload.message_id &&
        payload.chat_id
      ) {
        this.chatId = payload.chat_id;
        this.messageId = payload.message_id;
        // Manual acceptance may normalize away a passive prelude and attach
        // authored headings. Subsequent worker events must preserve that mapping.
        if (!this.segmentSequence.has(payload.segment_id)) this.segmentSequence.set(payload.segment_id, payload.sequence);
        if (payload.kind === "app_use_announcement") this.streamPreludeOffset = 1;
        const sourceChapter = this.source?.messageId === payload.message_id
          ? this.source.projected.find((item) => item.sequence === payload.sequence! - this.streamPreludeOffset)?.chapter : undefined;
        const presentation = this.presentationBySegmentId.get(payload.segment_id) ?? {
          ...defaultPresentation(payload.sequence, payload.kind),
          ...(sourceChapter ? { chapter: sourceChapter } : {}),
        };
        this.presentationBySegmentId.set(payload.segment_id, presentation);
        // Establish every segment before replaying early transport events. A
        // later clause's first observed status can already be ready, without a
        // stored asset; its buffered start/chunks still need an ordered slot.
        const placeholder: AssistantSpeechSegment = {
          id: payload.segment_id,
          sequence: payload.sequence,
          status: payload.status === "error" ? "failed" : "generating",
          durationMs: Math.max(0, Number(payload.duration_seconds ?? 0) * 1000),
          waveform: [],
          ...presentation,
        };
        if (this.queue.state.responseId !== payload.message_id || this.queue.state.status === "stopped") {
          this.queue.start(payload.message_id, [placeholder]);
        } else {
          this.queue.upsertSegment(placeholder);
        }
      }
      if (payload.status !== "ready") await this.hydrateReadySegment(payload);
      this.flushEarlyAudio(payload.segment_id);
      if (payload.status === "ready") await this.hydrateReadySegment(payload);
    }
  }

  private isCancelledStatus(status?: SpeechStatusSegment): boolean {
    return ["cancelled", "deleted", "invalidated"].includes(status?.status ?? "");
  }

  private async handleTurnStatus(payload: SpeechStatusPayload): Promise<void> {
    const id = payload.segment_id;
    if (!id || !/^(?:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(id)
      || !this.activeCallId || payload.voice_call_id !== this.activeCallId || payload.chat_id !== this.callOwner
      || !payload.message_id || payload.sequence !== 0 || !Number.isSafeInteger(payload.source_version) || payload.source_version! < 1
      || !Number.isSafeInteger(payload.execution_version) || payload.execution_version! < 1) return;
    if (this.turnTrack && this.turnTrack.messageId === payload.message_id &&
      (this.turnTrack.id !== id || this.turnTrack.sourceVersion !== payload.source_version
        || this.turnTrack.executionVersion !== payload.execution_version)) return;
    const latest = this.latestStatusBySegmentId.get(id);
    if (this.isCancelledStatus(latest) || this.olderAudioVersion(payload, latest ?? {})) return;
    if (this.turnTrack?.messageId !== payload.message_id) {
      this.supersedeCurrentMessage(payload.message_id);
      this.chatId = payload.chat_id!; this.messageId = payload.message_id;
      this.queue.start(payload.message_id, [{ id, sequence: 0, status: "generating", durationMs: 0,
        waveform: [], ...defaultPresentation(0, "voice_prose_turn") }]);
      this.turnTrack = { id, messageId: payload.message_id, sourceVersion: payload.source_version!, executionVersion: payload.execution_version! };
      this.queue.registerTurnTrack(id);
    }
    this.latestStatusBySegmentId.set(id, payload);
    this.segmentSequence.set(id, 0);
    this.liveCallSegmentIds.add(id);
    this.presentationBySegmentId.set(id, defaultPresentation(0, "voice_prose_turn"));
    if (payload.status === "error" || this.isCancelledStatus(payload)) {
      this.liveAudio.get(id)?.fail(); this.queue.fail(); this.publish(); return;
    }
    await this.hydrateReadySegment(payload);
    this.flushEarlyAudio(id);
  }

  private matchesLiveSeal(payload: SpeechStatusPayload): boolean {
    const seal = this.liveSeal;
    if (!seal || payload.message_id !== seal.messageId) return true;
    if (seal.failed) return false;
    if (!payload.segment_id || payload.sequence === -1) return true;
    if (payload.kind === "voice_prose_turn") return payload.segment_id === seal.trackId
      && payload.chat_id === seal.chatId && payload.voice_call_id === seal.callId && payload.source_version === seal.sourceVersion;
    return payload.chat_id === seal.chatId && payload.voice_call_id === seal.callId
      && payload.kind === "voice_prose_clause" && payload.source_version === seal.sourceVersion
      && seal.members.get(payload.segment_id) === payload.sequence;
  }

  private handleLiveSeal(payload: SpeechStatusPayload): void {
    if (!this.callOwner || !this.activeCallId || payload.voice_call_id !== this.activeCallId
      || payload.chat_id !== this.callOwner || !payload.message_id || payload.message_id.length > 128
      || !Number.isSafeInteger(payload.source_version) || payload.source_version! < 1
      || (payload.error !== undefined && payload.error !== LIVE_SEAL_ERROR)
      || !Array.isArray(payload.segments) || payload.segments.length > 1024) return;
    const failed = payload.error === LIVE_SEAL_ERROR;
    const members = new Map<string, number>();
    let previousSequence = -1;
    for (const row of payload.segments) {
      if (!row || typeof row !== "object" || Object.keys(row).length !== 4
        || !Object.keys(row).every((key) => ["segment_id", "sequence", "kind", "source_version"].includes(key))
        || typeof row.segment_id !== "string"
        || !/^(?:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(row.segment_id)
        || row.kind !== "voice_prose_clause" || row.source_version !== payload.source_version
        || !Number.isSafeInteger(row.sequence) || row.sequence! <= previousSequence || row.sequence! > 65_535
        || members.has(row.segment_id) || (!failed && this.isCancelledStatus(this.latestStatusBySegmentId.get(row.segment_id)))) return;
      const knownSequence = this.segmentSequence.get(row.segment_id);
      const known = this.audioAttempts.get(row.segment_id) ?? this.latestStatusBySegmentId.get(row.segment_id);
      if ((knownSequence !== undefined && knownSequence !== row.sequence)
        || (known?.source_version !== undefined && known.source_version !== payload.source_version)) return;
      members.set(row.segment_id, row.sequence!);
      previousSequence = row.sequence!;
    }
    if (this.turnTrack?.messageId === payload.message_id && payload.turn_track_id !== this.turnTrack.id) {
      this.queue.fail(); this.publish(); return;
    }
    const existing = this.liveSeal;
    if (existing && existing.messageId === payload.message_id && (existing.callId !== payload.voice_call_id
      || existing.sourceVersion !== payload.source_version || existing.members.size !== members.size
      || existing.failed !== failed || existing.trackId !== payload.turn_track_id
      || [...members].some(([id, sequence]) => existing.members.get(id) !== sequence))) return;

    this.supersedeCurrentMessage(payload.message_id);
    this.chatId = payload.chat_id;
    this.messageId = payload.message_id;
    this.liveSeal = { chatId: payload.chat_id, messageId: payload.message_id, callId: payload.voice_call_id,
      sourceVersion: payload.source_version!, members, failed, trackId: payload.turn_track_id };
    if (payload.turn_track_id !== undefined) {
      if (this.turnTrack?.id !== payload.turn_track_id || this.turnTrack.messageId !== payload.message_id) { this.queue.fail(); return; }
      this.queue.sealTurnTrack(payload.turn_track_id, [...members].map(([id,sequence]) => ({id,sequence})), failed);
      if (failed) this.liveAudio.get(payload.turn_track_id)?.fail();
      this.publish(); return;
    }
    for (const [id, pending] of this.earlyAudio) {
      if (pending.events[0]?.message_id === payload.message_id && pending.events[0]?.kind === "voice_prose_clause"
        && !members.has(id)) this.dropEarlyAudio(id);
    }
    for (const [id, presentation] of this.presentationBySegmentId) {
      if (presentation.kind !== "voice_prose_clause" || members.has(id)) continue;
      this.liveAudio.get(id)?.dispose();
      this.liveAudio.delete(id);
      this.dropEarlyAudio(id);
      this.audioAttempts.delete(id);
      this.latestStatusBySegmentId.delete(id);
      this.segmentSequence.delete(id);
      this.presentationBySegmentId.delete(id);
      this.liveCallSegmentIds.delete(id);
    }
    const placeholders: AssistantSpeechSegment[] = payload.segments.map((row) => {
      const id = row.segment_id!;
      const sequence = row.sequence!;
      this.segmentSequence.set(id, sequence);
      this.liveCallSegmentIds.add(id);
      const presentation = defaultPresentation(sequence, "voice_prose_clause");
      this.presentationBySegmentId.set(id, presentation);
      return { id, sequence, status: this.latestStatusBySegmentId.get(id)?.status === "error" ? "failed" : "generating",
        durationMs: 0, waveform: [], ...presentation };
    });
    if (this.queue.state.responseId !== payload.message_id) this.queue.start(payload.message_id, []);
    if (failed) this.error = LIVE_SEAL_ERROR;
    this.queue.sealLiveSegments(placeholders, failed);
    if (failed) {
      for (const stream of this.liveAudio.values()) stream.dispose();
      for (const [id, pending] of this.earlyAudio) {
        if (pending.events[0]?.message_id === payload.message_id) this.dropEarlyAudio(id);
      }
    } else {
      for (const id of members.keys()) this.flushEarlyAudio(id);
    }
    this.publish();
  }

  private olderAudioVersion(candidate: SpeechStatusSegment, current: SpeechStatusSegment): boolean {
    if (candidate.source_version !== undefined && current.source_version !== undefined
      && candidate.source_version !== current.source_version) return candidate.source_version < current.source_version;
    return candidate.execution_version !== undefined && current.execution_version !== undefined
      && candidate.execution_version < current.execution_version;
  }

  private retireAudioVersion(segmentId: string): void {
    this.queue.retireSegmentVersion(segmentId);
    this.liveAudio.get(segmentId)?.dispose();
    const oldKey = this.audioKeyBySegmentId.get(segmentId);
    if (oldKey) releaseCachedAudio(oldKey);
    this.audioKeyBySegmentId.delete(segmentId);
  }

  private handleAudio(payload: unknown): void {
    if (!isAssistantSpeechAudioEvent(payload) || !supportsAssistantSpeechStream()) return;
    if (!this.activeCallId || payload.voice_call_id !== this.activeCallId || payload.chat_id !== this.callOwner
      || this.stoppedMessageIds.has(payload.message_id) || this.dismissedMessageIds.has(payload.message_id)) return;
    if (this.turnTrack?.messageId === payload.message_id) {
      if (payload.kind === "voice_prose_clause") return;
      if (payload.kind === "voice_prose_turn" && (payload.segment_id !== this.turnTrack.id
        || payload.source_version !== this.turnTrack.sourceVersion || payload.execution_version !== this.turnTrack.executionVersion)) return;
    }
    if (!this.matchesLiveSeal(payload)) return;
    if (this.rejectedLiveAudio.has(payload.segment_id)) return;
    const status = this.latestStatusBySegmentId.get(payload.segment_id);
    if (this.isCancelledStatus(status) || this.olderAudioVersion(payload, status ?? {})) return;
    if (!this.segmentSequence.has(payload.segment_id) || !this.queue.segmentById(payload.segment_id)) {
      const size = payload.audio_data?.length ?? 0;
      let pending = this.earlyAudio.get(payload.segment_id);
      if ((!pending && this.earlyAudio.size >= MAX_EARLY_AUDIO_SEGMENTS)
        || this.earlyAudioBytes + size > MAX_EARLY_AUDIO_BYTES || (pending?.events.length ?? 0) >= 256) {
        this.rejectLiveAudio(payload.segment_id);
        return;
      }
      if (!pending) {
        pending = { events: [], bytes: 0,
          timer: setTimeout(() => this.rejectLiveAudio(payload.segment_id), EARLY_AUDIO_TIMEOUT_MS) };
        this.earlyAudio.set(payload.segment_id, pending);
      }
      pending.events.push(payload);
      pending.bytes += size;
      this.earlyAudioBytes += size;
      return;
    }
    // An early event may be retained for an unknown response, but no source is
    // attached until owner-scoped status binds that exact message and segment.
    if (payload.message_id !== this.messageId || this.queue.state.responseId !== payload.message_id) return;
    if (this.segmentSequence.get(payload.segment_id) !== payload.sequence
      || this.queue.segmentById(payload.segment_id)?.kind !== payload.kind) return;
    const current = this.audioAttempts.get(payload.segment_id);
    if (current && (this.olderAudioVersion(payload, current)
      || (payload.source_version === current.source_version && payload.execution_version === current.execution_version
        && payload.attempt_id !== current.attempt_id))) return;
    if (!current || current.attempt_id !== payload.attempt_id) {
      if (payload.phase !== "start" || payload.chunk_index !== 0) { this.rejectLiveAudio(payload.segment_id); return; }
      if (!current && this.audioAttempts.size >= MAX_AUDIO_ATTEMPTS) { this.rejectLiveAudio(payload.segment_id); return; }
      if (current) this.retireAudioVersion(payload.segment_id);
      this.audioAttempts.set(payload.segment_id, payload);
      if ([...this.liveAudio.values()].filter((stream) => stream.active).length >= MAX_LIVE_AUDIO_STREAMS) {
        this.rejectLiveAudio(payload.segment_id); return;
      }
      try {
        const stream = new AssistantSpeechStream(() => {
          if (this.liveAudio.get(payload.segment_id) === stream) {
            if (this.liveSeal?.failed && this.liveSeal.messageId === payload.message_id) return;
            this.queue.failStream(payload.segment_id, stream);
            this.error = "Live speech playback failed. Try speaking again.";
            this.publish();
          }
        }, payload.kind === "voice_prose_turn");
        this.liveAudio.set(payload.segment_id, stream);
        if (!this.queue.attachStream(payload.segment_id, stream)) { stream.dispose(); return; }
        stream.accept(payload);
      } catch {
        this.error = "Live speech playback failed. Try speaking again.";
        this.queue.invalidateSegment(payload.segment_id);
        this.publish();
      }
      return;
    }
    if (payload.source_version !== current.source_version || payload.execution_version !== current.execution_version) return;
    if (payload.phase !== "start") {
      const stream = this.liveAudio.get(payload.segment_id);
      stream?.accept(payload);
      if (payload.phase === "alignment" && stream?.active) this.queue.updateTurnTimings(payload.clause_timings!);
    }
  }

  private flushEarlyAudio(segmentId: string): void {
    const events = this.earlyAudio.get(segmentId)?.events;
    if (!events) return;
    this.dropEarlyAudio(segmentId);
    for (const event of events) this.handleAudio(event);
  }

  private dropEarlyAudio(segmentId: string): void {
    const pending = this.earlyAudio.get(segmentId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.earlyAudioBytes -= pending.bytes;
    this.earlyAudio.delete(segmentId);
  }

  private rejectLiveAudio(segmentId: string): void {
    this.dropEarlyAudio(segmentId);
    if (this.rejectedLiveAudio.size < MAX_AUDIO_ATTEMPTS) this.rejectedLiveAudio.add(segmentId);
    this.liveAudio.get(segmentId)?.dispose();
    this.queue.invalidateSegment(segmentId);
    this.error = "Live speech playback failed. Try speaking again.";
    this.publish();
  }

  private disposeLiveAudio(): void {
    for (const stream of this.liveAudio.values()) stream.dispose();
    this.liveAudio.clear();
    this.audioAttempts.clear();
    for (const id of this.liveCallSegmentIds) {
      this.latestStatusBySegmentId.delete(id);
      this.presentationBySegmentId.delete(id);
      this.segmentSequence.delete(id);
    }
    this.liveCallSegmentIds.clear();
    this.rejectedLiveAudio.clear();
    this.liveSeal = null;
    this.turnTrack = null;
    for (const id of this.earlyAudio.keys()) this.dropEarlyAudio(id);
    this.queue.disposeStreams();
  }

  private handleAcknowledgement(payload: SpeechAcknowledgementPayload): void {
    if (this.callOwner && payload.chat_id !== this.callOwner) return;
    if (!payload.chat_id || !payload.message_id || !payload.clip_id || !payload.audio_url) return;
    if (this.stoppedMessageIds.has(payload.message_id)) return;
    if (this.dismissedMessageIds.has(payload.message_id)) return;
    this.supersedeCurrentMessage(payload.message_id);
    this.chatId = payload.chat_id;
    this.messageId = payload.message_id;
    this.error = null;
    const acknowledgement: AssistantSpeechSegment = {
      id: `acknowledgement:${payload.clip_id}`,
      sequence: -1,
      status: "ready",
      durationMs: 0,
      audioUrl: payload.audio_url,
      playbackClass: "passive",
      chapter: { kind: "passive", type: "confirmation" },
      waveform: [],
    };
    if (this.queue.state.responseId === payload.message_id && this.queue.state.status !== "stopped") {
      this.queue.upsertSegment(acknowledgement);
    } else {
      this.queue.start(payload.message_id, [acknowledgement]);
    }
    this.publish();
  }

  private async hydrateReadySegment(status: SpeechStatusSegment): Promise<void> {
    if (!status.segment_id) return;
    if (this.isCancelledStatus(this.latestStatusBySegmentId.get(status.segment_id))) return;
    const sequence = this.segmentSequence.get(status.segment_id);
    if (sequence === undefined) return;
    const presentation = this.presentationBySegmentId.get(status.segment_id) ?? defaultPresentation(sequence, status.kind);
    if (this.liveCallSegmentIds.has(status.segment_id)
      || (this.activeCallId && ["voice_prose_clause", "waiting_confirmation", "voice_prose_turn"].includes(presentation.kind))) {
      const unsupported = !supportsAssistantSpeechStream();
      const invalidKind = !["voice_prose_clause", "waiting_confirmation", "voice_prose_turn"].includes(presentation.kind);
      this.queue.upsertSegment({ id: status.segment_id, sequence,
        status: unsupported || invalidKind || this.rejectedLiveAudio.has(status.segment_id) || status.status === "error" ? "failed" : "generating",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000), waveform: [], ...presentation });
      if (unsupported) this.error = "Live speech playback is not supported in this browser.";
      this.publish();
      return;
    }
    if (status.status !== "ready" || !status.generated_asset_id) {
      this.queue.upsertSegment({
        id: status.segment_id,
        sequence,
        status: status.status === "error" ? "failed" : "generating",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
        waveform: [],
        ...presentation,
      });
      if (status.status === "error") {
        this.error = this.queue.state.status === "failed" ? "Speech is temporarily unavailable." : null;
      }
      this.publish();
      return;
    }
    if (this.audioKeyBySegmentId.has(status.segment_id)) return;
    const generation = this.audioResolutionGeneration;
    const existingResolution = this.audioResolutionBySegmentId.get(status.segment_id);
    if (existingResolution) {
      await existingResolution.promise.catch(() => undefined);
      if (existingResolution.generation !== generation || existingResolution.assetId !== status.generated_asset_id) {
        await this.hydrateReadySegment(status);
      }
      return;
    }
    const expectedMessageId = this.messageId;
    const resolution = resolveGeneratedAudio(status.generated_asset_id);
    const resolutionRecord = { generation, assetId: status.generated_asset_id, promise: resolution };
    const isCurrentResolution = () => {
      const latest = this.latestStatusBySegmentId.get(status.segment_id!);
      const attempt = this.audioAttempts.get(status.segment_id!);
      return generation === this.audioResolutionGeneration && expectedMessageId === this.messageId
        && this.queue.state.status !== "stopped" && !this.isCancelledStatus(latest)
        && (!latest?.generated_asset_id || latest.generated_asset_id === status.generated_asset_id)
        && !this.olderAudioVersion(status, latest ?? {}) && (!attempt || !this.olderAudioVersion(status, attempt));
    };
    this.audioResolutionBySegmentId.set(status.segment_id, resolutionRecord);
    try {
      const resolvedAudio = await resolution;
      if (!isCurrentResolution()) {
        if (resolvedAudio.s3Key) releaseCachedAudio(resolvedAudio.s3Key);
        return;
      }
      if (resolvedAudio.s3Key) {
        this.audioKeyBySegmentId.set(status.segment_id, resolvedAudio.s3Key);
      }
      const recoveringActive = this.queue.state.status === "failed" && this.queue.state.activeSegmentId === status.segment_id;
      if (recoveringActive) this.error = null;
      this.queue.upsertSegment({
        id: status.segment_id,
        sequence,
        status: "ready",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
        audioUrl: resolvedAudio.url,
        waveform: [],
        ...presentation,
      });
      this.publish();
      void buildWaveformFromAudioUrl(resolvedAudio.url)
        .then((waveform) => {
          if (!isCurrentResolution()) return;
          this.queue.upsertSegment({
            id: status.segment_id!,
            sequence,
            status: "ready",
            durationMs: Math.max(0, Number(status.duration_seconds ?? waveform.duration_seconds ?? 0) * 1000),
            audioUrl: resolvedAudio.url,
            waveform: waveform.samples,
            ...presentation,
          });
          this.publish();
        })
        .catch((cause) => console.error("[AssistantSpeechController] Waveform extraction failed:", cause));
    } catch (cause) {
      if (!isCurrentResolution()) return;
      console.error("[AssistantSpeechController] Generated audio could not be resolved:", cause);
      this.error = "Speech audio could not be loaded.";
      this.queue.upsertSegment({
        id: status.segment_id,
        sequence,
        status: "failed",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
        waveform: [],
        ...presentation,
      });
      this.publish();
    } finally {
      if (this.audioResolutionBySegmentId.get(status.segment_id) === resolutionRecord) {
        this.audioResolutionBySegmentId.delete(status.segment_id);
      }
    }
  }

  private supersedeCurrentMessage(nextMessageId: string): void {
    if (this.messageId && this.messageId !== nextMessageId) {
      const nextSource = this.source?.messageId === nextMessageId ? this.source : null;
      const nextEarlyAudio = [...this.earlyAudio.values()].flatMap(({ events }) => events.filter((event) => event.message_id === nextMessageId));
      this.rememberStoppedMessage(this.messageId);
      this.audioResolutionGeneration += 1;
      this.queue.stop();
      this.segmentSequence.clear();
      this.presentationBySegmentId.clear();
      this.latestStatusBySegmentId.clear();
      this.pending = null;
      this.lastRequest = null;
      this.source = nextSource;
      this.generationRequestedIds.clear();
      this.waitingForSource.clear();
      this.streamPreludeOffset = 0;
      this.releaseGeneratedAudio();
      for (const event of nextEarlyAudio) this.handleAudio(event);
      if (this.chatId) void webSocketService.sendMessage("assistant_speech", { action: "cancel", chat_id: this.chatId, assistant_message_id: this.messageId })
        .catch((cause) => console.error("[AssistantSpeechController] Superseded speech cancellation failed:", cause));
    }
  }

  private releaseGeneratedAudio(): void {
    this.disposeLiveAudio();
    for (const s3Key of Array.from(this.audioKeyBySegmentId.values())) {
      releaseCachedAudio(s3Key);
    }
    this.audioKeyBySegmentId.clear();
  }

  private rememberStoppedMessage(messageId: string): void {
    this.stoppedMessageIds.add(messageId);
    if (this.stoppedMessageIds.size <= MAX_STOPPED_MESSAGE_IDS) return;
    const oldestMessageId = this.stoppedMessageIds.values().next().value;
    if (oldestMessageId) this.stoppedMessageIds.delete(oldestMessageId);
  }

  private publish(): void {
    const source = this.canonicalSource;
    this.activity.set({
      chatId: source?.chatId ?? this.chatId,
      messageId: source?.messageId ?? this.messageId,
      text: source?.text ?? "",
      speaking: this.queue.state.status === "playing" && (!source || source.messageId === this.messageId),
      language: get(locale) || "en",
    });
    this.player.set({
      ...this.queue.state,
      chatId: this.chatId,
      messageId: this.messageId,
      regions: this.queue.waveformRegions,
      // A prefetched chapter can fail while the current audio is still playing.
      // Keep its failure in the queue; show recovery when that chapter is active.
      error: this.queue.state.status === "failed" ? (this.error || "Speech is temporarily unavailable.") : null,
      presentationMode: this.queue.presentationMode,
      hasReplayableTracks: this.queue.hasReplayableTracks,
      mateName: this.mateName,
      mateCategory: this.mateCategory,
    });
  }
}

function projectAssistantSpeech(markdown: string): ProjectedSpeechSegment[] {
  // The locale supplies new historical fallbacks. Replay resolves these finite
  // phrases to existing canonical audio in the original response language.
  return projectSharedAssistantSpeech(markdown, get(locale) || "en").map((segment) => ({
    sequence: segment.sequence,
    kind: segment.kind,
    speakable_text: segment.speakableText,
    source_version: 1,
    source_hash: "server-verified",
    chapter: segment.chapter,
  }));
}

function defaultPresentation(sequence: number, kind = "prose_paragraph"): {
  chapter: AssistantSpeechChapter;
  kind: string;
  playbackClass: "passive" | "replayable";
} {
  if (kind === "app_use_announcement" || kind === "waiting_confirmation") {
    return { chapter: { kind: "passive", type: kind === "waiting_confirmation" ? "confirmation" : "using_apps" }, kind, playbackClass: "passive" };
  }
  const semanticType = kind === "code_summary" ? "code" : kind === "table_summary" ? "table" : kind === "embed_summary" ? "structured" : null;
  return {
    chapter: semanticType ? { kind: "semantic", type: semanticType } : { kind: "part", number: sequence + 1 },
    kind,
    playbackClass: "replayable",
  };
}

async function resolveGeneratedAudio(assetId: string): Promise<{ url: string; s3Key: string | null }> {
  for (let attempt = 0; attempt < GENERATED_ASSET_RETRY_COUNT; attempt += 1) {
    const embed = await resolveEmbed(assetId) ?? await resolveEmbed(`embed:${assetId}`);
    const decoded = typeof embed?.content === "string"
      ? await decodeToonContent(embed.content)
      : embed;
    const content = decoded ?? embed;
    const url = findDownloadUrl(content);
    if (url) return { url, s3Key: null };
    const encryptedAudio = getEncryptedAudio(content);
    if (encryptedAudio) {
      const decryptedUrl = await fetchAndDecryptAudio(
        encryptedAudio.s3BaseUrl,
        encryptedAudio.s3Key,
        encryptedAudio.aesKey,
        encryptedAudio.aesNonce,
        encryptedAudio.mimeType,
        encryptedAudio.variant,
      );
      return { url: decryptedUrl, s3Key: encryptedAudio.s3Key };
    }
    await new Promise((resolve) => setTimeout(resolve, GENERATED_ASSET_RETRY_MS));
  }
  throw new Error(`Generated assistant speech asset ${assetId} was not available`);
}

function getEncryptedAudio(value: unknown): {
  s3BaseUrl: string;
  s3Key: string;
  aesKey: string;
  aesNonce: string;
  mimeType: string;
  variant: Record<string, unknown>;
} | null {
  if (!value || typeof value !== "object") return null;
  const content = value as Record<string, unknown>;
  const files = content.files && typeof content.files === "object"
    ? content.files as Record<string, unknown>
    : null;
  const variant = files?.original && typeof files.original === "object"
    ? files.original as Record<string, unknown>
    : {};
  const s3Key = stringValue(variant.s3_key) || stringValue(content.files_original_s3_key);
  const aesKey = stringValue(content.aes_key);
  if (!s3Key || !aesKey) return null;
  return {
    s3BaseUrl: stringValue(content.s3_base_url),
    s3Key,
    aesKey,
    aesNonce: stringValue(content.aes_nonce),
    mimeType: stringValue(variant.mime_type) || stringValue(content.mime_type) || "audio/mpeg",
    variant,
  };
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function findDownloadUrl(value: unknown): string | null {
  if (typeof value === "string") {
    return value.includes("/v1/generated-assets/") ? value : null;
  }
  if (!value || typeof value !== "object") return null;
  for (const child of Object.values(value as Record<string, unknown>)) {
    const found = findDownloadUrl(child);
    if (found) return found;
  }
  return null;
}

export const assistantSpeechController = new AssistantSpeechController();
