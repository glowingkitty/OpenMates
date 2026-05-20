// frontend/packages/ui/src/services/handlersCodeRunOutputs.ts
//
// Receive-side handling for encrypted Code Run terminal-output sidecars.
// Decrypts with the embed key, writes IndexedDB, then notifies open fullscreen
// components so output appears across devices without a page refresh.

import { chatDB } from "./db";
import { decryptWithEmbedKey } from "./encryption/MetadataEncryptor";
import { upsertCodeRunOutput as idbUpsertCodeRunOutput } from "./db/codeRunOutputs";
import { embedStore } from "./embedStore";
import type { CodeRunOutput, CodeRunOutputSyncedPayload } from "../types/chat";

function parseEvents(value: unknown): CodeRunOutput["events"] {
  if (!Array.isArray(value)) return undefined;
  return value.filter((event): event is { kind: string; text: string; timestamp: number } => {
    if (!event || typeof event !== "object") return false;
    const candidate = event as Record<string, unknown>;
    return (
      typeof candidate.kind === "string"
      && typeof candidate.text === "string"
      && typeof candidate.timestamp === "number"
    );
  });
}

async function decryptIntoOutput(
  payload: CodeRunOutputSyncedPayload,
): Promise<CodeRunOutput | null> {
  const embedKey = await embedStore.getEmbedKey(payload.embed_id);
  if (!embedKey) {
    console.warn(
      `[handlersCodeRunOutputs] no embed key for embed ${payload.embed_id} — dropping Code Run output ${payload.id}`,
    );
    return null;
  }

  const plaintext = await decryptWithEmbedKey(payload.encrypted_payload, embedKey, {
    embedId: payload.embed_id,
    chatId: payload.chat_id,
    fieldName: "code_run_output",
  });
  if (!plaintext) return null;
  let plain: Record<string, unknown>;
  try {
    plain = JSON.parse(plaintext) as Record<string, unknown>;
  } catch (error) {
    console.error("[handlersCodeRunOutputs] Failed to parse Code Run output payload", error);
    return null;
  }
  if (!plain) return null;

  const output = plain.output;
  const savedAt = plain.saved_at;
  if (typeof output !== "string" || typeof savedAt !== "number") return null;

  return {
    id: payload.id,
    chat_id: payload.chat_id,
    embed_id: payload.embed_id,
    author_user_id: payload.author_user_id,
    output,
    status: typeof plain.status === "string" ? plain.status : undefined,
    files: Array.isArray(plain.files)
      ? plain.files.filter((file): file is string => typeof file === "string")
      : undefined,
    events: parseEvents(plain.events),
    saved_at: savedAt,
    created_at: typeof plain.created_at === "number" ? plain.created_at : payload.created_at,
    updated_at: typeof plain.updated_at === "number" ? plain.updated_at : payload.updated_at,
    key_version: payload.key_version ?? null,
  };
}

export async function handleCodeRunOutputSyncedImpl(payload: unknown): Promise<void> {
  const output = await decryptIntoOutput(payload as CodeRunOutputSyncedPayload);
  if (!output) return;
  try {
    await idbUpsertCodeRunOutput(chatDB, output);
  } catch (error) {
    console.error("[handlersCodeRunOutputs] IDB upsert failed", error);
  }
  window.dispatchEvent(new CustomEvent("codeRunOutputSynced", { detail: output }));
}
