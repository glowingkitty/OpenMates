// frontend/packages/ui/src/services/chatSyncVersionPlans.ts
// Version-wins plans of inbound chat updates, extracted verbatim from
// chatSyncServiceHandlersChatUpdates.ts (encrypted_chat_metadata versions,
// draft_deleted staleness, chat_message_confirmed messages_v) and
// chatSyncServiceHandlersCoreSync.ts (Phase 1b and on-demand batch messages_v).
// Default builds run the TypeScript below; the opt-in shared Rust core build
// (VITE_OPENMATES_RUST_CORE) asks the shared Worker `sync` unit instead
// (web_sync/versions.rs, proven by web_sync/versions_vectors.json) with no
// TypeScript fallback. Only version numbers cross to the Worker.
import type { Chat } from "../types/chat";
import { RUST_UPDATES_POLICY } from "./chatSyncUpdatesPolicy";

/** Answers the version plans from the shared Rust Worker (const-false in default builds). */
export const VERSION_PLANS_IN_RUST = RUST_UPDATES_POLICY;

/** Version counters an encrypted_chat_metadata broadcast may carry. */
export type MetadataVersionKey = "messages_v" | "metadata_v" | "title_v" | "draft_v";
export type MetadataVersions = Partial<Record<MetadataVersionKey, number>>;
type LocalVersions = Pick<Chat, "messages_v" | "title_v" | "draft_v"> & { metadata_v?: number | null };

export interface MetadataVersionPlan {
  /** False when an older metadata revision must not overwrite title/summary/follow-up. */
  acceptsRevision: boolean;
  /** Version keys to copy from the broadcast's `versions`, in apply order. */
  apply: MetadataVersionKey[];
}

export interface DraftDeletedPlan {
  ignore: "versionless" | "stale" | null;
  /** New `cleared_draft_v` when the deletion is admitted. */
  clearedDraftV: number | null;
}

export interface MessagesVersionPlan {
  messagesV: number;
  /** Strictly ahead of `local || 0`. */
  advanced: boolean;
}

/** Flag-off encrypted_chat_metadata version plan. */
export function metadataVersionPlanTs(local: LocalVersions, versions: MetadataVersions | undefined): MetadataVersionPlan {
  const incomingMetadataV = versions?.metadata_v;
  const localMetadataV = local.metadata_v || local.title_v || 0;
  const acceptsRevision = incomingMetadataV === undefined || incomingMetadataV >= localMetadataV;
  const apply: MetadataVersionKey[] = [];
  if (versions) {
    if (versions.messages_v !== undefined && versions.messages_v > (local.messages_v || 0)) {
      apply.push("messages_v");
    }
    if (versions.metadata_v !== undefined && acceptsRevision) {
      apply.push("metadata_v");
      if (versions.title_v !== undefined) apply.push("title_v");
    } else if (versions.title_v !== undefined && versions.title_v > (local.title_v || 0)) {
      apply.push("title_v");
    }
    if (versions.draft_v !== undefined && versions.draft_v > (local.draft_v || 0)) {
      apply.push("draft_v");
    }
  }
  return { acceptsRevision, apply };
}

/** Flag-off draft_deleted plan against an existing local chat. */
export function draftDeletedPlanTs(
  local: Pick<Chat, "draft_v" | "cleared_draft_v">,
  draftV: number | undefined,
): DraftDeletedPlan {
  const localDraftVersion = Math.max(local.draft_v ?? 0, local.cleared_draft_v ?? 0);
  if (draftV === undefined && localDraftVersion > 0) return { ignore: "versionless", clearedDraftV: null };
  if (draftV !== undefined && localDraftVersion > draftV) return { ignore: "stale", clearedDraftV: null };
  return { ignore: null, clearedDraftV: Math.max(local.cleared_draft_v ?? 0, draftV ?? local.draft_v ?? 0) };
}

/** Flag-off forward-only messages_v advance: `Math.max(local || 0, ...candidates)`. */
export function messagesVersionTs(local: number | null | undefined, candidates: number[]): MessagesVersionPlan {
  const base = local || 0;
  const messagesV = Math.max(base, ...candidates);
  return { messagesV, advanced: messagesV > base };
}

function versionOps() {
  return import("./rustCore/sync/versionOps");
}

/** Rust encrypted_chat_metadata version plan (shared Worker `sync` unit). */
export async function metadataVersionPlanRust(local: LocalVersions, versions: MetadataVersions | undefined) {
  return (await versionOps()).metadataVersions(local, versions);
}

/** Rust draft_deleted plan. */
export async function draftDeletedPlanRust(local: Pick<Chat, "draft_v" | "cleared_draft_v">, draftV: number | undefined) {
  return (await versionOps()).draftDeleted(local, draftV);
}

/** Rust messages_v advance. */
export async function messagesVersionRust(local: number | null | undefined, candidates: number[]) {
  return (await versionOps()).messagesVersion(local, candidates);
}
