// assistantSpeechController.ts
// Bridges assistant message text, owner-scoped WebSocket status, generated assets,
// and the browser-only AssistantSpeechQueue. Only transient projected text leaves
// this module; status handling and player state never expose persisted plaintext.
// One controller instance owns playback across the application.

import { writable } from "svelte/store";
import {
  fetchAndDecryptAudio,
  releaseCachedAudio,
} from "../components/embeds/audio/audioEmbedCrypto";
import { decodeToonContent, resolveEmbed } from "./embedResolver";
import {
  AssistantSpeechQueue,
  type AssistantSpeechQueueState,
  type AssistantSpeechSegment,
  type AssistantSpeechWaveformRegion,
} from "./assistantSpeechQueue";
import { webSocketService } from "./websocketService";
import { projectAssistantSpeech as projectSharedAssistantSpeech } from "../../../assistantSpeechProjection";

interface ProjectedSpeechSegment {
  sequence: number;
  kind: string;
  speakable_text: string;
  source_version: number;
  source_hash: string;
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
}

export interface PublicAssistantSpeechSegment {
  segment_id: string;
  sequence: number;
  public_url: string;
  duration_seconds: number;
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
  private chatId: string | null = null;
  private messageId: string | null = null;
  private error: string | null = null;
  private readonly stoppedMessageIds = new Set<string>();
  private readonly audioKeyBySegmentId = new Map<string, string>();
  private readonly audioResolutionBySegmentId = new Map<string, {
    generation: number;
    promise: Promise<{ url: string; s3Key: string | null }>;
  }>();
  private audioResolutionGeneration = 0;
  private publicPlayback = false;

  constructor() {
    webSocketService.on<SpeechStatusPayload>("assistant_speech_status", (payload) => {
      void this.handleStatus(payload);
    });
    webSocketService.on<SpeechAcknowledgementPayload>("assistant_speech_acknowledgement", (payload) => {
      this.handleAcknowledgement(payload);
    });
  }

  async request(chatId: string, messageId: string, markdown: string): Promise<void> {
    const projected = projectAssistantSpeech(markdown);
    if (projected.length === 0) return;
    this.supersedeCurrentMessage(messageId);
    this.pending = { chatId, messageId, projected };
    this.stoppedMessageIds.delete(messageId);
    this.chatId = chatId;
    this.messageId = messageId;
    this.error = null;
    this.publicPlayback = false;
    this.publish();
    await webSocketService.sendMessage("assistant_speech", {
      action: "request",
      chat_id: chatId,
      assistant_message_id: messageId,
      segments: projected,
    });
  }

  pause(): void { this.queue.pause(); }
  play(): Promise<void> { return this.queue.play(); }
  previous(): Promise<void> { return this.queue.previous(); }
  next(): Promise<void> { return this.queue.next(); }
  selectSegment(segmentId: string): Promise<void> { return this.queue.selectSegment(segmentId); }
  continueAfterUserGesture(): Promise<void> { return this.queue.continueAfterUserGesture(); }

  async playPublicExample(chatId: string, messageId: string, fixtures: PublicAssistantSpeechSegment[]): Promise<void> {
    if (fixtures.length === 0) return;
    await this.stop();
    this.pending = null;
    this.stoppedMessageIds.delete(messageId);
    this.chatId = chatId;
    this.messageId = messageId;
    this.error = null;
    this.publicPlayback = true;
    this.queue.start(messageId, fixtures.map((fixture) => ({
      id: fixture.segment_id,
      sequence: fixture.sequence,
      status: "ready",
      durationMs: Math.max(0, fixture.duration_seconds * 1000),
      audioUrl: fixture.public_url,
      playbackClass: "replayable",
    })));
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
    if (payload.message_id) this.supersedeCurrentMessage(payload.message_id);
    if (payload.status === "accepted" && payload.segments && this.pending) {
      const { chatId, messageId, projected } = this.pending;
      this.pending = null;
      this.chatId = chatId;
      this.messageId = messageId;
      this.segmentSequence.clear();
      const segments = payload.segments.flatMap((status, index) => {
        if (!status.segment_id || !projected[index]) return [];
        const sequence = status.sequence ?? projected[index].sequence;
        this.segmentSequence.set(status.segment_id, sequence);
        return [{
          id: status.segment_id,
          sequence,
          status: status.status === "ready" ? "ready" : status.status === "error" ? "failed" : "generating",
          durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
          playbackClass: status.kind === "app_use_announcement" ? "passive" : "replayable",
        } satisfies AssistantSpeechSegment];
      });
      if (this.queue.state.responseId === messageId && this.queue.state.status !== "stopped") {
        for (const segment of segments) this.queue.upsertSegment(segment);
      } else {
        this.queue.start(messageId, segments);
      }
      await Promise.all(payload.segments.map((status) => this.hydrateReadySegment(status)));
      return;
    }

    if (payload.status === "error" && !payload.segment_id) {
      this.error = "Speech is temporarily unavailable.";
      this.publish();
      return;
    }
    if (payload.segment_id) {
      if (
        typeof payload.sequence === "number" &&
        payload.message_id &&
        payload.chat_id
      ) {
        this.chatId = payload.chat_id;
        this.messageId = payload.message_id;
        this.segmentSequence.set(payload.segment_id, payload.sequence);
        if (this.queue.state.responseId !== payload.message_id || this.queue.state.status === "stopped") {
          this.queue.start(payload.message_id, [{
            id: payload.segment_id,
            sequence: payload.sequence,
            status: payload.status === "ready" ? "ready" : payload.status === "error" ? "failed" : "generating",
            durationMs: Math.max(0, Number(payload.duration_seconds ?? 0) * 1000),
            playbackClass: payload.kind === "app_use_announcement" ? "passive" : "replayable",
          }]);
        }
      }
      await this.hydrateReadySegment(payload);
    }
  }

  private handleAcknowledgement(payload: SpeechAcknowledgementPayload): void {
    if (!payload.chat_id || !payload.message_id || !payload.clip_id || !payload.audio_url) return;
    if (this.stoppedMessageIds.has(payload.message_id)) return;
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
    if (status.status !== "ready" || !status.generated_asset_id) {
      this.queue.upsertSegment({
        id: status.segment_id,
        sequence,
        status: status.status === "error" ? "failed" : "generating",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
        playbackClass: status.kind === "app_use_announcement" ? "passive" : "replayable",
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
      this.queue.upsertSegment({
        id: status.segment_id,
        sequence,
        status: "ready",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
        audioUrl: resolvedAudio.url,
        playbackClass: status.kind === "app_use_announcement" ? "passive" : "replayable",
      });
      this.publish();
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
        playbackClass: status.kind === "app_use_announcement" ? "passive" : "replayable",
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
      }));
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
