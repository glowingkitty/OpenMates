// assistantSpeechController.ts
// Bridges assistant message text, owner-scoped WebSocket status, generated assets,
// and the browser-only AssistantSpeechQueue. Only transient projected text leaves
// this module; status handling and player state never expose persisted plaintext.
// One controller instance owns playback across the application.

import { writable, type Readable } from "svelte/store";
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
import { projectAssistantSpeech as projectSharedAssistantSpeech } from "../../../assistantSpeechProjection";

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
  status?: "accepted" | "queued" | "generating" | "ready" | "error" | "cancelled" | "deleted";
  generated_asset_id?: string;
  duration_seconds?: number;
  retryable?: boolean;
  sequence?: number;
  kind?: string;
}

interface SpeechStatusPayload extends SpeechStatusSegment {
  chat_id?: string;
  message_id?: string;
  segments?: SpeechStatusSegment[];
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

class AssistantSpeechController {
  readonly player = writable<AssistantSpeechPlayerState>(INITIAL_PLAYER_STATE);
  private readonly queue = new AssistantSpeechQueue({
    onStateChange: () => this.publish(),
  });
  private pending: {
    chatId: string;
    messageId: string;
    projected: ProjectedSpeechSegment[];
  } | null = null;
  private segmentSequence = new Map<string, number>();
  private readonly latestStatusBySegmentId = new Map<string, SpeechStatusSegment>();
  private lastRequest: { chatId: string; messageId: string; projected: ProjectedSpeechSegment[] } | null = null;
  private chatId: string | null = null;
  private messageId: string | null = null;
  private error: string | null = null;
  private readonly stoppedMessageIds = new Set<string>();
  private readonly dismissedMessageIds = new Set<string>();
  private readonly audioKeyBySegmentId = new Map<string, string>();
  private readonly audioResolutionBySegmentId = new Map<string, {
    generation: number;
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
        for (const status of this.latestStatusBySegmentId.values()) {
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
  }

  async request(
    chatId: string,
    messageId: string,
    markdown: string,
    mate: { name?: string; category?: string } = {},
  ): Promise<void> {
    const projected = projectAssistantSpeech(markdown);
    if (projected.length === 0) return;
    this.supersedeCurrentMessage(messageId);
    this.pending = { chatId, messageId, projected };
    this.lastRequest = this.pending;
    this.stoppedMessageIds.delete(messageId);
    this.dismissedMessageIds.delete(messageId);
    this.chatId = chatId;
    this.messageId = messageId;
    this.error = null;
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
  async play(): Promise<void> {
    if (this.queue.state.status === "failed") {
      const activeId = this.queue.state.activeSegmentId;
      const ready = activeId ? this.latestStatusBySegmentId.get(activeId) : undefined;
      this.error = null;
      if (ready?.status === "ready") {
        await this.hydrateReadySegment(ready);
      } else if (this.lastRequest) {
        this.pending = this.lastRequest;
        if (ready) {
          await this.hydrateReadySegment({ ...ready, status: "queued" });
        } else if (!activeId) {
          this.queue.start(this.lastRequest.messageId, []);
        }
        await this.sendRequest();
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
        segments: request.projected.map(({ chapter: _chapter, ...segment }) => segment),
      });
    } catch (cause) {
      if (this.messageId !== request.messageId) return;
      console.error("[AssistantSpeechController] Speech request failed:", cause);
      this.error = "Speech is temporarily unavailable.";
      this.queue.fail();
    }
  }
  previous(): Promise<void> { return this.queue.previous(); }
  next(): Promise<void> { return this.queue.next(); }
  selectSegment(segmentId: string): Promise<void> { return this.queue.selectSegment(segmentId); }
  continueAfterUserGesture(): Promise<void> { return this.queue.continueAfterUserGesture(); }

  async close(): Promise<void> {
    if (this.messageId) this.dismissedMessageIds.add(this.messageId);
    this.audioResolutionGeneration += 1;
    this.queue.stop();
    this.lastRequest = null;
    this.pending = null;
    this.releaseGeneratedAudio();
  }

  async playPublicExample(chatId: string, messageId: string, fixtures: PublicAssistantSpeechSegment[]): Promise<void> {
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
    if (this.messageId) this.rememberStoppedMessage(this.messageId);
    this.audioResolutionGeneration += 1;
    this.queue.stop();
    this.releaseGeneratedAudio();
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
    const statusMessageId = payload.message_id ?? this.pending?.messageId;
    if (statusMessageId && this.stoppedMessageIds.has(statusMessageId)) return;
    if (statusMessageId && this.dismissedMessageIds.has(statusMessageId)) return;
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
        const sequence = (status.sequence ?? projected[index]?.sequence ?? index) - sequenceOffset;
        const source = projected.find((segment) => segment.sequence === sequence);
        if (!status.segment_id || !source) return [];
        const latest = this.latestStatusBySegmentId.get(status.segment_id);
        if (latest?.status === "ready") status = { ...status, ...latest };
        this.latestStatusBySegmentId.set(status.segment_id, status);
        this.segmentSequence.set(status.segment_id, sequence);
        const presentation = {
          chapter: source.chapter,
          kind: status.kind || source.kind,
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
      if (this.queue.state.responseId === messageId && this.queue.state.status !== "stopped") {
        for (const segment of segments) this.queue.upsertSegment(segment);
      } else {
        this.queue.start(messageId, segments);
      }
      this.queue.markComplete();
      await Promise.all(payload.segments.map((status) => this.hydrateReadySegment(this.latestStatusBySegmentId.get(status.segment_id ?? "") ?? status)));
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
      if (latest?.status === "ready" && ["queued", "generating"].includes(payload.status ?? "")) return;
      this.latestStatusBySegmentId.set(payload.segment_id, payload);
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
        const presentation = this.presentationBySegmentId.get(payload.segment_id) ?? defaultPresentation(payload.sequence, payload.kind);
        this.presentationBySegmentId.set(payload.segment_id, presentation);
        if (this.queue.state.responseId !== payload.message_id || this.queue.state.status === "stopped") {
          this.queue.start(payload.message_id, [{
            id: payload.segment_id,
            sequence: payload.sequence,
            status: payload.status === "ready" ? "ready" : payload.status === "error" ? "failed" : "generating",
            durationMs: Math.max(0, Number(payload.duration_seconds ?? 0) * 1000),
            waveform: [],
            ...presentation,
          }]);
        }
      }
      await this.hydrateReadySegment(payload);
    }
  }

  private handleAcknowledgement(payload: SpeechAcknowledgementPayload): void {
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
    const sequence = this.segmentSequence.get(status.segment_id);
    if (sequence === undefined) return;
    const presentation = this.presentationBySegmentId.get(status.segment_id) ?? defaultPresentation(sequence, status.kind);
    if (status.status !== "ready" || !status.generated_asset_id) {
      if (status.status === "error") this.error = "Speech is temporarily unavailable.";
      this.queue.upsertSegment({
        id: status.segment_id,
        sequence,
        status: status.status === "error" ? "failed" : "generating",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
        waveform: [],
        ...presentation,
      });
      this.publish();
      return;
    }
    if (this.audioKeyBySegmentId.has(status.segment_id)) return;
    const generation = this.audioResolutionGeneration;
    const existingResolution = this.audioResolutionBySegmentId.get(status.segment_id);
    if (existingResolution) {
      await existingResolution.promise.catch(() => undefined);
      if (existingResolution.generation !== generation) {
        await this.hydrateReadySegment(status);
      }
      return;
    }
    const expectedMessageId = this.messageId;
    const resolution = resolveGeneratedAudio(status.generated_asset_id);
    const resolutionRecord = { generation, promise: resolution };
    this.audioResolutionBySegmentId.set(status.segment_id, resolutionRecord);
    try {
      const resolvedAudio = await resolution;
      if (
        generation !== this.audioResolutionGeneration ||
        expectedMessageId !== this.messageId ||
        this.queue.state.status === "stopped"
      ) {
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
          if (generation !== this.audioResolutionGeneration || expectedMessageId !== this.messageId) return;
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
      if (
        generation !== this.audioResolutionGeneration ||
        expectedMessageId !== this.messageId ||
        this.queue.state.status === "stopped"
      ) return;
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
      this.rememberStoppedMessage(this.messageId);
      this.audioResolutionGeneration += 1;
      this.queue.stop();
      this.segmentSequence.clear();
      this.presentationBySegmentId.clear();
      this.latestStatusBySegmentId.clear();
      this.pending = null;
      this.lastRequest = null;
      this.releaseGeneratedAudio();
    }
  }

  private releaseGeneratedAudio(): void {
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
    this.player.set({
      ...this.queue.state,
      chatId: this.chatId,
      messageId: this.messageId,
      regions: this.queue.waveformRegions,
      error: this.error,
      presentationMode: this.queue.presentationMode,
      hasReplayableTracks: this.queue.hasReplayableTracks,
      mateName: this.mateName,
      mateCategory: this.mateCategory,
    });
  }
}

function projectAssistantSpeech(markdown: string): ProjectedSpeechSegment[] {
  return projectSharedAssistantSpeech(markdown).map((segment) => ({
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
  if (kind === "app_use_announcement") {
    return { chapter: { kind: "passive", type: "using_apps" }, kind, playbackClass: "passive" };
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
