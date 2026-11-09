// frontend/packages/ui/src/types/recommendations.ts
//
// Wire and storage contract for chat Recommendations (memory and workflow
// recommendations shown in the Recommendations card, which replaced quick tips).
// Plan: docs/plans/chat-recommendations/plan.yml
// Spec: specifications/features/app-memories/specification.yml
//   (app-memories.recommendations.*)
//
// Server -> client: post_processing_completed.recommendations: ChatRecommendation[]
// Client storage:   chats.encrypted_recommendations = encryptWithChatKey(JSON.stringify(ChatRecommendationsState))
// Duplicate/dismiss policy runs in the Rust client core (reconcile), never here.

/** Kind of entry a recommendation would create or update. */
export type ChatRecommendationKind = 'memory' | 'workflow';

/** Whether the recommendation creates a new entry or updates an existing one. */
export type ChatRecommendationAction = 'create' | 'update';

/** One recommendation as produced by post-processing (metadata only). */
export interface ChatRecommendation {
  /** Stable id (server-derived from task id, kind and index). */
  id: string;
  kind: ChatRecommendationKind;
  action: ChatRecommendationAction;
  /** Existing memory id or workflow id when action is 'update', else null. */
  target_id: string | null;
  /** Short title, at most 80 characters. */
  title: string;
  /** One or two sentences, at most 200 characters. */
  summary: string;
}

/** Plaintext of chats.encrypted_recommendations (encrypted with the chat key). */
export interface ChatRecommendationsState {
  schema_version: 1;
  /** Open recommendations of the latest completed turn, after reconcile. */
  items: ChatRecommendation[];
  /** Normalized titles the user dismissed in this chat; never re-proposed here. */
  dismissed: string[];
  /** Normalized titles the user saved from this chat; never re-proposed here. */
  resolved: string[];
  /** Unix seconds of the last change. */
  updated_at: number;
}

/** Local memory metadata passed to the Rust reconcile step (never sent to the server). */
export interface LocalMemoryMetadata {
  id: string;
  title: string;
  when_to_use: string;
}

/** Input of the Rust core reconcile function. */
export interface ReconcileRecommendationsInput {
  incoming: ChatRecommendation[];
  dismissed: string[];
  resolved: string[];
  /** All locally decrypted memories, including Mention only ones. */
  local_memories: LocalMemoryMetadata[];
}

/** Plaintext of the encrypted role:system chat message written when the user saves. */
export interface ContextEntryHistoryEvent {
  schema_version: 1;
  type: 'context_entry';
  kind: ChatRecommendationKind;
  action: 'created' | 'updated';
  entry_id: string;
  title: string;
  /** Unix seconds. */
  created_at: number;
}
