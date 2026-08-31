// assistantSpeechController.ts
// Bridges assistant message text, owner-scoped WebSocket status, generated assets,
// and the browser-only AssistantSpeechQueue. Only transient projected text leaves
// this module; status handling and player state never expose persisted plaintext.
// One controller instance owns playback across the application.

import { writable } from "svelte/store";
import { decodeToonContent, resolveEmbed } from "./embedResolver";
import {
  AssistantSpeechQueue,
  type AssistantSpeechQueueState,
  type AssistantSpeechSegment,
  type AssistantSpeechWaveformRegion,
} from "./assistantSpeechQueue";
import { webSocketService } from "./websocketService";

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
}

interface SpeechStatusPayload extends SpeechStatusSegment {
  chat_id?: string;
  message_id?: string;
  segments?: SpeechStatusSegment[];
}

export interface AssistantSpeechPlayerState extends AssistantSpeechQueueState {
  chatId: string | null;
  messageId: string | null;
  regions: AssistantSpeechWaveformRegion[];
  error: string | null;
}

const INITIAL_PLAYER_STATE: AssistantSpeechPlayerState = {
  responseId: null,
  chatId: null,
  messageId: null,
  status: "idle",
  activeSegmentId: null,
  regions: [],
  error: null,
};
const GENERATED_ASSET_RETRY_MS = 150;
const GENERATED_ASSET_RETRY_COUNT = 20;

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

  constructor() {
    webSocketService.on<SpeechStatusPayload>("assistant_speech_status", (payload) => {
      void this.handleStatus(payload);
    });
  }

  async request(chatId: string, messageId: string, markdown: string): Promise<void> {
    const projected = projectAssistantSpeech(markdown);
    if (projected.length === 0) return;
    this.pending = { chatId, messageId, projected };
    this.chatId = chatId;
    this.messageId = messageId;
    this.error = null;
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

  async stop(): Promise<void> {
    this.queue.stop();
    if (this.chatId && this.messageId) {
      await webSocketService.sendMessage("assistant_speech", {
        action: "cancel",
        chat_id: this.chatId,
        assistant_message_id: this.messageId,
      });
    }
  }

  private async handleStatus(payload: SpeechStatusPayload): Promise<void> {
    if (payload.status === "accepted" && payload.segments && this.pending) {
      const { chatId, messageId, projected } = this.pending;
      this.pending = null;
      this.chatId = chatId;
      this.messageId = messageId;
      this.segmentSequence.clear();
      const segments = payload.segments.flatMap((status, index) => {
        if (!status.segment_id || !projected[index]) return [];
        this.segmentSequence.set(status.segment_id, projected[index].sequence);
        return [{
          id: status.segment_id,
          sequence: projected[index].sequence,
          status: status.status === "ready" ? "ready" : status.status === "error" ? "failed" : "generating",
          durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
        } satisfies AssistantSpeechSegment];
      });
      this.queue.start(messageId, segments);
      await Promise.all(payload.segments.map((status) => this.hydrateReadySegment(status)));
      return;
    }

    if (payload.status === "error") {
      this.error = "Speech is temporarily unavailable.";
      this.publish();
      return;
    }
    if (payload.segment_id) await this.hydrateReadySegment(payload);
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
      });
      this.publish();
      return;
    }
    try {
      const audioUrl = await resolveGeneratedAudioUrl(status.generated_asset_id);
      this.queue.upsertSegment({
        id: status.segment_id,
        sequence,
        status: "ready",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
        audioUrl,
      });
      this.publish();
    } catch (cause) {
      console.error("[AssistantSpeechController] Generated audio could not be resolved:", cause);
      this.error = "Speech audio could not be loaded.";
      this.queue.upsertSegment({
        id: status.segment_id,
        sequence,
        status: "failed",
        durationMs: Math.max(0, Number(status.duration_seconds ?? 0) * 1000),
      });
      this.publish();
    }
  }

  private publish(): void {
    this.player.set({
      ...this.queue.state,
      chatId: this.chatId,
      messageId: this.messageId,
      regions: this.queue.waveformRegions,
      error: this.error,
    });
  }
}

function projectAssistantSpeech(markdown: string): ProjectedSpeechSegment[] {
  return markdown
    .split(/\n\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .flatMap(splitLongParagraph)
    .slice(0, 20)
    .map((paragraph, sequence) => {
      const projected = projectParagraph(paragraph);
      return {
        sequence,
        kind: projected.kind,
        speakable_text: projected.text,
        source_version: 1,
        source_hash: "server-verified",
      };
    })
    .filter((segment) => segment.speakable_text.length > 0);
}

function splitLongParagraph(paragraph: string): string[] {
  const chunks: string[] = [];
  let remainder = paragraph;
  while (remainder.length > 2000) {
    let boundary = remainder.lastIndexOf(" ", 2000);
    if (boundary <= 0) boundary = 2000;
    chunks.push(remainder.slice(0, boundary).trim());
    remainder = remainder.slice(boundary).trimStart();
  }
  if (remainder) chunks.push(remainder);
  return chunks;
}

function projectParagraph(markdown: string): { kind: string; text: string } {
  const trimmed = markdown.trim();
  if (/^```[\s\S]*```$/.test(trimmed)) return { kind: "code_summary", text: "A code example is available." };
  const lines = trimmed.split("\n").filter((line) => line.trim());
  if (lines.length >= 2 && lines.every((line) => /^\s*\|.*\|\s*$/.test(line))) {
    return { kind: "table_summary", text: "A table is available." };
  }
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    return { kind: "embed_summary", text: "Structured data is available." };
  }
  const text = trimmed
    .replace(/```[\s\S]*?```/g, " A code example is available. ")
    .replace(/^\s*\|.*\|\s*$/gm, " A table is available. ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`[^`]*`/g, "")
    .replace(/(?:https?|ftp):\/\/[^\s)\]>]+|[a-z][a-z0-9+.-]*:\/\/[^\s)\]>]+/gi, "")
    .replace(/(?:^|\s)[#>*_~]+|[_~]{1,3}/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/^[\s,;:-]+|[\s,;:-]+$/g, "");
  return { kind: "prose_paragraph", text };
}

async function resolveGeneratedAudioUrl(assetId: string): Promise<string> {
  for (let attempt = 0; attempt < GENERATED_ASSET_RETRY_COUNT; attempt += 1) {
    const embed = await resolveEmbed(assetId) ?? await resolveEmbed(`embed:${assetId}`);
    const decoded = typeof embed?.content === "string"
      ? await decodeToonContent(embed.content)
      : embed;
    const url = findDownloadUrl(decoded ?? embed);
    if (url) return url;
    await new Promise((resolve) => setTimeout(resolve, GENERATED_ASSET_RETRY_MS));
  }
  throw new Error(`Generated assistant speech asset ${assetId} was not available`);
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
