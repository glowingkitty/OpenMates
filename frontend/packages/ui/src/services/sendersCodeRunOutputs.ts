// frontend/packages/ui/src/services/sendersCodeRunOutputs.ts
//
// WebSocket senders for Code Run terminal-output sidecars. Payloads are
// encrypted with the embed key and stored as separate rows so run output never
// rewrites the canonical code embed content.

import { chatDB } from "./db";
import { webSocketService } from "./websocketService";
import { encryptWithEmbedKey } from "./encryption/MetadataEncryptor";
import { upsertCodeRunOutput as idbUpsertCodeRunOutput } from "./db/codeRunOutputs";
import { embedStore } from "./embedStore";
import type { CodeRunOutput, CodeRunOutputPayload } from "../types/chat";

export async function sendUpsertCodeRunOutputImpl(
  output: CodeRunOutput,
): Promise<void> {
  const cloneSafeOutput: CodeRunOutput = {
    ...output,
    files: output.files?.map((file) => String(file)),
    events: output.events?.map(({ kind, text, timestamp }) => ({
      kind,
      text: String(text),
      timestamp: Number(timestamp),
    })),
  };

  const embedKey = await embedStore.getEmbedKey(cloneSafeOutput.embed_id);
  if (!embedKey) {
    throw new Error(
      `[sendersCodeRunOutputs] No embed key for embed ${cloneSafeOutput.embed_id} — cannot encrypt Code Run output`,
    );
  }

  const payload: CodeRunOutputPayload = {
    output: cloneSafeOutput.output,
    status: cloneSafeOutput.status,
    files: cloneSafeOutput.files,
    events: cloneSafeOutput.events,
    saved_at: cloneSafeOutput.saved_at,
    created_at: cloneSafeOutput.created_at,
    updated_at: cloneSafeOutput.updated_at,
  };
  const encrypted_payload = await encryptWithEmbedKey(JSON.stringify(payload), embedKey);

  try {
    await idbUpsertCodeRunOutput(chatDB, cloneSafeOutput);
    window.dispatchEvent(new CustomEvent("codeRunOutputSynced", { detail: cloneSafeOutput }));
  } catch (error) {
    console.error("[sendersCodeRunOutputs] IDB upsert failed", error);
  }

  try {
    await webSocketService.sendMessage("upsert_code_run_output", {
      chat_id: cloneSafeOutput.chat_id,
      embed_id: cloneSafeOutput.embed_id,
      id: cloneSafeOutput.id,
      key_version: cloneSafeOutput.key_version ?? null,
      encrypted_payload,
      inference_payload: payload,
      created_at: cloneSafeOutput.created_at,
      updated_at: cloneSafeOutput.updated_at ?? cloneSafeOutput.created_at,
    });
  } catch (error) {
    console.error("[sendersCodeRunOutputs] WS upsert failed", error);
  }
}

export async function sendRequestCodeRunOutputImpl(
  chatId: string,
  embedId: string,
): Promise<void> {
  try {
    await webSocketService.sendMessage("request_code_run_output", {
      chat_id: chatId,
      embed_id: embedId,
    });
  } catch (error) {
    console.error("[sendersCodeRunOutputs] WS request failed", error);
  }
}
