// frontend/packages/ui/src/stores/workflowTemplateProjectionStore.ts
// Local index for encrypted Workflow template projections.
// It stores only ciphertext and a master-key-wrapped template key, never the
// portable projection plaintext or a share-link fragment key.
// The backend remains the source of truth for public retrieval and revocation.

import { writable } from "svelte/store";

export type WorkflowTemplateProjectionLocalRecord = {
  workflowId: string;
  templateId: string;
  sourceVersion: number;
  ciphertext: string;
  ciphertextChecksum: string;
  ownerWrappedKey: string;
  projectionSchemaVersion: number;
  shortToken?: string;
  revokedAt?: number | null;
  updatedAt: number;
};

type WorkflowTemplateProjectionState = Record<string, WorkflowTemplateProjectionLocalRecord>;

const STORAGE_KEY = "openmates.workflow-template-projections.v1";

function loadInitialState(): WorkflowTemplateProjectionState {
  if (typeof window === "undefined") return {};
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) return {};
    const parsed = JSON.parse(stored) as unknown;
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? parsed as WorkflowTemplateProjectionState
      : {};
  } catch (error) {
    console.warn("[WorkflowTemplateProjectionStore] Could not restore local projection index:", error);
    return {};
  }
}

const store = writable<WorkflowTemplateProjectionState>(loadInitialState());

function persist(state: WorkflowTemplateProjectionState): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    console.warn("[WorkflowTemplateProjectionStore] Could not persist local projection index:", error);
  }
}

export const workflowTemplateProjectionStore = {
  subscribe: store.subscribe,

  get(workflowId: string): WorkflowTemplateProjectionLocalRecord | null {
    let record: WorkflowTemplateProjectionLocalRecord | null = null;
    const unsubscribe = store.subscribe((state) => {
      record = state[workflowId] ?? null;
    });
    unsubscribe();
    return record;
  },

  upsert(record: WorkflowTemplateProjectionLocalRecord): void {
    store.update((state) => {
      const next = { ...state, [record.workflowId]: record };
      persist(next);
      return next;
    });
  },

  setRevoked(workflowId: string, revokedAt: number | null): void {
    store.update((state) => {
      const existing = state[workflowId];
      if (!existing) return state;
      const next = {
        ...state,
        [workflowId]: { ...existing, revokedAt, updatedAt: Date.now() },
      };
      persist(next);
      return next;
    });
  },
};
