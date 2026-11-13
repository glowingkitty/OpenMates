// frontend/packages/ui/src/services/shareState/shareMetadataQueuePolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Record building, request bodies and retry rules of shareMetadataQueue.ts.
// IndexedDB, fetch and timers stay in the queue service; with
// VITE_OPENMATES_RUST_CORE=1 the shared Rust core decides (web_share_state).
// An absent field means `undefined` (dropped by JSON.stringify), `null` stays null.

const MAX_RETRY_COUNT = 5;

export interface ChatRecordInput {
  update_id: string;
  chat_id: string;
  title: string | null;
  summary: string | null;
  share_cta_text?: string | null;
  encrypted_shared_short_url?: string | null;
  share_pii?: boolean;
  share_highlights?: boolean;
  now_ms: number;
}

export function queueChatRecord(input: ChatRecordInput) {
  return {
    update_id: input.update_id,
    chat_id: input.chat_id,
    title: input.title,
    summary: input.summary,
    share_cta_text: input.share_cta_text,
    encrypted_shared_short_url: input.encrypted_shared_short_url,
    share_pii: input.share_pii,
    share_highlights: input.share_highlights,
    created_at: Math.floor(input.now_ms / 1000),
    retry_count: 0,
  };
}

export function queueEmbedRecord(input: {
  update_id: string; embed_id: string; is_shared: boolean;
  title?: string | null; description?: string | null; now_ms: number;
}) {
  return {
    update_id: input.update_id,
    embed_id: input.embed_id,
    is_shared: input.is_shared,
    title: input.title,
    description: input.description,
    created_at: Math.floor(input.now_ms / 1000),
    retry_count: 0,
  };
}

/** Body of POST /v1/share/chat/metadata. */
export function queueChatBody(input: {
  chat_id: string; title: string | null; summary: string | null; share_cta_text?: string | null;
  encrypted_shared_short_url?: string | null; is_shared: boolean; share_pii?: boolean; share_highlights?: boolean;
}) {
  const requestBody: Record<string, unknown> = {
    chat_id: input.chat_id,
    title: input.title || null,
    summary: input.summary || null,
    share_cta_text: input.share_cta_text || input.summary || null,
    is_shared: input.is_shared,
    share_pii: input.share_pii,
    share_highlights: input.share_highlights,
  };
  if (input.encrypted_shared_short_url !== undefined) {
    requestBody.encrypted_shared_short_url = input.encrypted_shared_short_url;
  }
  return requestBody;
}

/** Body of POST /v1/share/embed/metadata. */
export function queueEmbedBody(input: {
  embed_id: string; is_shared: boolean; title?: string | null; description?: string | null;
}) {
  return {
    embed_id: input.embed_id,
    is_shared: input.is_shared,
    title: input.title || null,
    description: input.description || null,
  };
}

/** A pending update that was tried the maximum number of times is dropped. */
export function queueRetryDecision(input: { retry_count: number }): "drop" | "send" {
  return input.retry_count >= MAX_RETRY_COUNT ? "drop" : "send";
}

/** Delete a delivered update; keep a failed one with its retry count incremented. */
export function queueAttemptOutcome(input: { success: boolean; retry_count: number }) {
  return input.success
    ? { action: "delete" as const }
    : { action: "store" as const, retry_count: input.retry_count + 1 };
}

export function queueResponseSuccess(input: { body: { success?: unknown } | null | undefined }): boolean {
  return input.body?.success === true;
}

export const QUEUE_OPS = {
  queueChatRecord, queueEmbedRecord, queueChatBody, queueEmbedBody,
  queueRetryDecision, queueAttemptOutcome, queueResponseSuccess,
};
