// frontend/packages/ui/src/services/handlersNotebookRunOutputs.ts
//
// Receive-side handling for encrypted notebook-run output sidecars. The server
// only routes ciphertext; this client decrypts with the notebook embed key,
// writes IndexedDB, then notifies open notebook components.

import { chatDB } from "./db";
import { decryptWithEmbedKey } from "./encryption/MetadataEncryptor";
import { upsertNotebookRunOutput as idbUpsertNotebookRunOutput } from "./db/notebookRunOutputs";
import { embedStore } from "./embedStore";
import type { NotebookCellRunOutput, NotebookRunOutput, NotebookRunOutputSyncedPayload } from "../types/chat";

function parseCellOutputs(value: unknown): NotebookCellRunOutput[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const candidate = item as Record<string, unknown>;
    if (typeof candidate.cell_index !== "number") return [];
    return [{
      cell_index: candidate.cell_index,
      execution_count: typeof candidate.execution_count === "number" ? candidate.execution_count : null,
      outputs: Array.isArray(candidate.outputs) ? candidate.outputs : [],
    }];
  });
}

function parseSelectedCellIndices(value: unknown): number[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const indices = value.filter((index): index is number => Number.isInteger(index));
  return indices.length > 0 ? indices : undefined;
}

async function decryptIntoOutput(
  payload: NotebookRunOutputSyncedPayload,
): Promise<NotebookRunOutput | null> {
  const embedKey = await embedStore.getEmbedKey(payload.notebook_embed_id);
  if (!embedKey) {
    console.warn(
      `[handlersNotebookRunOutputs] no embed key for notebook ${payload.notebook_embed_id} — dropping notebook output ${payload.id}`,
    );
    return null;
  }

  const plaintext = await decryptWithEmbedKey(payload.encrypted_payload, embedKey, {
    embedId: payload.notebook_embed_id,
    chatId: payload.chat_id,
    fieldName: "notebook_run_output",
  });
  if (!plaintext) return null;
  let plain: Record<string, unknown>;
  try {
    plain = JSON.parse(plaintext) as Record<string, unknown>;
  } catch (error) {
    console.error("[handlersNotebookRunOutputs] Failed to parse notebook output payload", error);
    return null;
  }

  const cellOutputs = parseCellOutputs(plain.cell_outputs);
  const savedAt = plain.saved_at;
  if (cellOutputs.length === 0 || typeof savedAt !== "number") return null;

  return {
    id: payload.id,
    chat_id: payload.chat_id,
    notebook_embed_id: payload.notebook_embed_id,
    author_user_id: payload.author_user_id,
    source_version: typeof plain.source_version === "string" ? plain.source_version : payload.source_version ?? null,
    status: typeof plain.status === "string" ? plain.status : undefined,
    selected_cell_indices: parseSelectedCellIndices(plain.selected_cell_indices),
    cell_outputs: cellOutputs,
    error: typeof plain.error === "string" ? plain.error : undefined,
    saved_at: savedAt,
    created_at: typeof plain.created_at === "number" ? plain.created_at : payload.created_at,
    updated_at: typeof plain.updated_at === "number" ? plain.updated_at : payload.updated_at,
    key_version: payload.key_version ?? null,
  };
}

export async function handleNotebookRunOutputSyncedImpl(payload: unknown): Promise<void> {
  const output = await decryptIntoOutput(payload as NotebookRunOutputSyncedPayload);
  if (!output) return;
  try {
    await idbUpsertNotebookRunOutput(chatDB, output);
  } catch (error) {
    console.error("[handlersNotebookRunOutputs] IDB upsert failed", error);
  }
  window.dispatchEvent(new CustomEvent("notebookRunOutputSynced", { detail: output }));
}
