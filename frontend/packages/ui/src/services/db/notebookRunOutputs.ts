// frontend/packages/ui/src/services/db/notebookRunOutputs.ts
//
// IndexedDB data access for decrypted notebook-run output sidecars. Rows are
// stored locally after decrypting the server sidecar and never mutate the
// canonical notebook embed source.

import type { NotebookRunOutput } from "../../types/chat";

const STORE_NAME = "notebook_run_outputs";

type NotebookRunOutputsDb = {
  db: IDBDatabase | null;
  NOTEBOOK_RUN_OUTPUTS_STORE_NAME: string;
};

function assertDb(instance: NotebookRunOutputsDb): IDBDatabase {
  if (!instance.db) throw new Error("[notebookRunOutputs] DB not initialized");
  return instance.db;
}

export async function upsertNotebookRunOutput(
  instance: NotebookRunOutputsDb,
  output: NotebookRunOutput,
): Promise<void> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    tx.objectStore(STORE_NAME).put(output);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function getNotebookRunOutputForEmbed(
  instance: NotebookRunOutputsDb,
  notebookEmbedId: string,
): Promise<NotebookRunOutput | null> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readonly");
    const index = tx.objectStore(STORE_NAME).index("notebook_embed_id");
    const req = index.getAll(IDBKeyRange.only(notebookEmbedId));
    req.onsuccess = () => {
      const rows = ((req.result ?? []) as NotebookRunOutput[])
        .sort((a, b) => (b.updated_at ?? b.created_at) - (a.updated_at ?? a.created_at));
      resolve(rows[0] ?? null);
    };
    req.onerror = () => reject(req.error);
  });
}

export async function getNotebookRunOutputsForChat(
  instance: NotebookRunOutputsDb,
  chatId: string,
): Promise<NotebookRunOutput[]> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readonly");
    const index = tx.objectStore(STORE_NAME).index("chat_id");
    const req = index.getAll(IDBKeyRange.only(chatId));
    req.onsuccess = () => resolve((req.result ?? []) as NotebookRunOutput[]);
    req.onerror = () => reject(req.error);
  });
}
