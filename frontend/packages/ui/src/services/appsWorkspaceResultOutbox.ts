/** Durable, account-scoped ciphertext waiting for an Apps result upload. */

export type AppsResultStatus = "processing" | "finished" | "error" | "cancelled";

export type AppsCipherRow = {
  embed_id: string;
  encrypted_type: string;
  encrypted_content: string;
  encrypted_text_preview?: string;
  status: AppsResultStatus;
  embed_ids?: string[];
  parent_embed_id?: string;
};

export type AppsResultGraph = {
  app_id: string;
  skill_id: string;
  root_embed_id: string;
  team_id?: string;
  embeds: AppsCipherRow[];
  linked_embed_ids?: string[];
  encrypted_embed_key: string;
  created_at: number;
};

export type PendingAppsResult = {
  id: string;
  userId: string;
  teamId: string | null;
  rootEmbedId: string;
  revision: string;
  graph: AppsResultGraph;
  deferredChildIds?: string[];
  updatedAt: number;
};

type StoredPendingAppsResult = PendingAppsResult & { teamScope: string };

const DB_NAME = "openmates_apps_result_outbox";
const DB_VERSION = 1;
const STORE_NAME = "pending_results";
const SCOPE_INDEX = "owner_team";

export function makePendingAppsResultId(userId: string, teamId: string | null, rootEmbedId: string): string {
  return JSON.stringify([userId, teamId, rootEmbedId]);
}

function teamScope(teamId: string | null): string {
  return JSON.stringify(teamId);
}

function openOutboxDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB unavailable"));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    let blocked = false;
    request.onupgradeneeded = () => {
      const store = request.result.objectStoreNames.contains(STORE_NAME)
        ? request.transaction!.objectStore(STORE_NAME)
        : request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
      if (!store.indexNames.contains(SCOPE_INDEX)) {
        store.createIndex(SCOPE_INDEX, ["userId", "teamScope"]);
      }
    };
    request.onsuccess = () => {
      if (blocked) request.result.close();
      else resolve(request.result);
    };
    request.onerror = () => reject(request.error ?? new Error("Failed to open Apps result outbox"));
    request.onblocked = () => {
      blocked = true;
      reject(new Error("Apps result outbox upgrade blocked"));
    };
  });
}

function validateRecord(record: PendingAppsResult): void {
  if (!record.userId || !record.rootEmbedId || !record.revision ||
      record.id !== makePendingAppsResultId(record.userId, record.teamId, record.rootEmbedId) ||
      record.graph.root_embed_id !== record.rootEmbedId ||
      (record.graph.team_id ?? null) !== record.teamId) {
    throw new Error("Invalid Apps result outbox scope");
  }
}

/** Copy only encrypted fields so accidental plaintext additions never reach disk. */
function storedRecord(record: PendingAppsResult): StoredPendingAppsResult {
  const graph = record.graph;
  return {
    id: record.id,
    userId: record.userId,
    teamId: record.teamId,
    teamScope: teamScope(record.teamId),
    rootEmbedId: record.rootEmbedId,
    revision: record.revision,
    updatedAt: record.updatedAt,
    ...(record.deferredChildIds === undefined ? {} : { deferredChildIds: [...record.deferredChildIds] }),
    graph: {
      app_id: graph.app_id,
      skill_id: graph.skill_id,
      root_embed_id: graph.root_embed_id,
      ...(graph.team_id === undefined ? {} : { team_id: graph.team_id }),
      embeds: graph.embeds.map((row) => ({
        embed_id: row.embed_id,
        encrypted_type: row.encrypted_type,
        encrypted_content: row.encrypted_content,
        ...(row.encrypted_text_preview === undefined ? {} : { encrypted_text_preview: row.encrypted_text_preview }),
        status: row.status,
        ...(row.embed_ids === undefined ? {} : { embed_ids: [...row.embed_ids] }),
        ...(row.parent_embed_id === undefined ? {} : { parent_embed_id: row.parent_embed_id }),
      })),
      ...(graph.linked_embed_ids === undefined ? {} : { linked_embed_ids: [...graph.linked_embed_ids] }),
      encrypted_embed_key: graph.encrypted_embed_key,
      created_at: graph.created_at,
    },
  };
}

function publicRecord(record: StoredPendingAppsResult): PendingAppsResult {
  const { teamScope: _teamScope, ...pending } = record;
  return pending;
}

async function withTransaction<T>(mode: IDBTransactionMode, operation: (store: IDBObjectStore, setResult: (value: T) => void) => void): Promise<T> {
  const db = await openOutboxDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      let result: T;
      let tx: IDBTransaction | undefined;
      try {
        tx = db.transaction(STORE_NAME, mode);
        tx.oncomplete = () => resolve(result);
        tx.onerror = () => reject(tx.error ?? new Error("Apps result outbox transaction failed"));
        tx.onabort = () => reject(tx.error ?? new Error("Apps result outbox transaction aborted"));
        operation(tx.objectStore(STORE_NAME), (value) => { result = value; });
      } catch (error) {
        try { tx?.abort(); } catch { /* The original error is more useful. */ }
        reject(error);
      }
    });
  } finally {
    db.close();
  }
}

export async function stagePendingAppsResult(record: PendingAppsResult): Promise<void> {
  validateRecord(record);
  await withTransaction<void>("readwrite", (store) => { store.put(storedRecord(record)); });
}

export async function getPendingAppsResult(userId: string, teamId: string | null, rootEmbedId: string): Promise<PendingAppsResult | undefined> {
  const id = makePendingAppsResultId(userId, teamId, rootEmbedId);
  return withTransaction<PendingAppsResult | undefined>("readonly", (store, setResult) => {
    const request = store.get(id);
    request.onsuccess = () => {
      const row = request.result as StoredPendingAppsResult | undefined;
      setResult(row && row.userId === userId && row.teamId === teamId ? publicRecord(row) : undefined);
    };
  });
}

export async function listPendingAppsResults(userId: string, teamId: string | null): Promise<PendingAppsResult[]> {
  return withTransaction<PendingAppsResult[]>("readonly", (store, setResult) => {
    const request = store.index(SCOPE_INDEX).getAll(IDBKeyRange.only([userId, teamScope(teamId)]));
    request.onsuccess = () => setResult((request.result as StoredPendingAppsResult[]).map(publicRecord));
  });
}

/** An upload acknowledgement may only clear the revision it actually uploaded. */
export async function deletePendingAppsResult(record: PendingAppsResult): Promise<void> {
  validateRecord(record);
  await withTransaction<void>("readwrite", (store) => {
    const request = store.get(record.id);
    request.onsuccess = () => {
      const current = request.result as StoredPendingAppsResult | undefined;
      if (current?.revision === record.revision && current.userId === record.userId && current.teamId === record.teamId) {
        store.delete(record.id);
      }
    };
  });
}
