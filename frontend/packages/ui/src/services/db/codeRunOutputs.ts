// frontend/packages/ui/src/services/db/codeRunOutputs.ts
//
// IndexedDB data-access for Code Run terminal-output sidecars. Rows are stored
// decrypted locally after the chat-key encrypted payload is received or created.
// The canonical code embed content is never modified by these helpers.

import type { CodeRunOutput } from "../../types/chat";

const STORE_NAME = "code_run_outputs";

type CodeRunOutputsDb = {
  db: IDBDatabase | null;
  CODE_RUN_OUTPUTS_STORE_NAME: string;
};

function assertDb(instance: CodeRunOutputsDb): IDBDatabase {
  if (!instance.db) throw new Error("[codeRunOutputs] DB not initialized");
  return instance.db;
}

export async function upsertCodeRunOutput(
  instance: CodeRunOutputsDb,
  output: CodeRunOutput,
): Promise<void> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    tx.objectStore(STORE_NAME).put(output);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function getCodeRunOutputForEmbed(
  instance: CodeRunOutputsDb,
  embedId: string,
): Promise<CodeRunOutput | null> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readonly");
    const index = tx.objectStore(STORE_NAME).index("embed_id");
    const req = index.getAll(IDBKeyRange.only(embedId));
    req.onsuccess = () => {
      const rows = ((req.result ?? []) as CodeRunOutput[])
        .sort((a, b) => (b.updated_at ?? b.created_at) - (a.updated_at ?? a.created_at));
      resolve(rows[0] ?? null);
    };
    req.onerror = () => reject(req.error);
  });
}

export async function getCodeRunOutputsForChat(
  instance: CodeRunOutputsDb,
  chatId: string,
): Promise<CodeRunOutput[]> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readonly");
    const index = tx.objectStore(STORE_NAME).index("chat_id");
    const req = index.getAll(IDBKeyRange.only(chatId));
    req.onsuccess = () => resolve((req.result ?? []) as CodeRunOutput[]);
    req.onerror = () => reject(req.error);
  });
}
