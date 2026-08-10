// frontend/packages/ui/src/services/sendersNotebookRunOutputs.ts
//
// WebSocket senders for notebook-run output sidecars. The payload is encrypted
// with the notebook embed key and stored separately from the canonical `.ipynb`
// source embed.

import { chatDB } from "./db";
import { webSocketService } from "./websocketService";
import { encryptWithEmbedKey } from "./encryption/MetadataEncryptor";
import { upsertNotebookRunOutput as idbUpsertNotebookRunOutput } from "./db/notebookRunOutputs";
import { embedStore } from "./embedStore";
import type { NotebookRunOutput, NotebookRunOutputPayload } from "../types/chat";

export async function sendUpsertNotebookRunOutputImpl(
  output: NotebookRunOutput,
): Promise<void> {
  const cloneSafeOutput: NotebookRunOutput = {
    ...output,
    selected_cell_indices: output.selected_cell_indices?.map((index) => Number(index)),
    cell_outputs: output.cell_outputs.map((cellOutput) => ({
      cell_index: Number(cellOutput.cell_index),
      execution_count: cellOutput.execution_count ?? null,
      outputs: Array.isArray(cellOutput.outputs) ? cellOutput.outputs : [],
    })),
  };

  const embedKey = await embedStore.getEmbedKey(cloneSafeOutput.notebook_embed_id);
  if (!embedKey) {
    throw new Error(
      `[sendersNotebookRunOutputs] No embed key for embed ${cloneSafeOutput.notebook_embed_id} — cannot encrypt notebook output`,
    );
  }

  const payload: NotebookRunOutputPayload = {
    source_version: cloneSafeOutput.source_version ?? null,
    status: cloneSafeOutput.status,
    selected_cell_indices: cloneSafeOutput.selected_cell_indices,
    cell_outputs: cloneSafeOutput.cell_outputs,
    error: cloneSafeOutput.error,
    saved_at: cloneSafeOutput.saved_at,
    created_at: cloneSafeOutput.created_at,
    updated_at: cloneSafeOutput.updated_at,
  };
  const encrypted_payload = await encryptWithEmbedKey(JSON.stringify(payload), embedKey);

  try {
    await idbUpsertNotebookRunOutput(chatDB, cloneSafeOutput);
    window.dispatchEvent(new CustomEvent("notebookRunOutputSynced", { detail: cloneSafeOutput }));
  } catch (error) {
    console.error("[sendersNotebookRunOutputs] IDB upsert failed", error);
  }

  try {
    await webSocketService.sendMessage("upsert_notebook_run_output", {
      chat_id: cloneSafeOutput.chat_id,
      notebook_embed_id: cloneSafeOutput.notebook_embed_id,
      id: cloneSafeOutput.id,
      source_version: cloneSafeOutput.source_version ?? null,
      key_version: cloneSafeOutput.key_version ?? null,
      encrypted_payload,
      created_at: cloneSafeOutput.created_at,
      updated_at: cloneSafeOutput.updated_at ?? cloneSafeOutput.created_at,
    });
  } catch (error) {
    console.error("[sendersNotebookRunOutputs] WS upsert failed", error);
  }
}

export async function sendRequestNotebookRunOutputImpl(
  chatId: string,
  notebookEmbedId: string,
): Promise<void> {
  try {
    await webSocketService.sendMessage("request_notebook_run_output", {
      chat_id: chatId,
      notebook_embed_id: notebookEmbedId,
    });
  } catch (error) {
    console.error("[sendersNotebookRunOutputs] WS request failed", error);
  }
}
