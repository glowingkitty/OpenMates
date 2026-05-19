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
  const embedKey = await embedStore.getEmbedKey(output.embed_id);
  if (!embedKey) {
    throw new Error(
      `[sendersCodeRunOutputs] No embed key for embed ${output.embed_id} — cannot encrypt Code Run output`,
    );
  }

  const payload: CodeRunOutputPayload = {
    output: output.output,
    status: output.status,
    files: output.files,
    events: output.events,
    saved_at: output.saved_at,
    created_at: output.created_at,
    updated_at: output.updated_at,
  };
  const encrypted_payload = await encryptWithEmbedKey(JSON.stringify(payload), embedKey);

  try {
    await idbUpsertCodeRunOutput(chatDB, output);
  } catch (error) {
    console.error("[sendersCodeRunOutputs] IDB upsert failed", error);
  }

  try {
    await webSocketService.sendMessage("upsert_code_run_output", {
      chat_id: output.chat_id,
      embed_id: output.embed_id,
      id: output.id,
      key_version: output.key_version ?? null,
      encrypted_payload,
      created_at: output.created_at,
      updated_at: output.updated_at ?? output.created_at,
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
