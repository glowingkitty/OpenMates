import { get } from "svelte/store";
import { chatDB } from "../db";
import { activeTeamContext, isActiveTeamContext } from "../../stores/teamStore";
import type { ChatSynchronizationService } from "../chatSyncService";
import { draftEditorUIState } from "./draftState";
import type { Chat } from "../../types/chat";

export interface DraftChatContext {
  teamId: string | null;
  epoch: number;
  committed: boolean;
}

// The persisted Chat intent survives lost message ACKs and workspace switches.
// This generation is only a same-runtime cancellation fence for an in-flight
// promotion. A delete takes effect here synchronously, before its first await.
const draftDeleteGenerations = new Map<string, number>();
const draftTransports = new Map<string, Promise<void>>();

export function cancelTeamDraftPromotion(chatId: string): void {
  draftDeleteGenerations.set(chatId, (draftDeleteGenerations.get(chatId) ?? 0) + 1);
}

export async function withSerializedDraftTransport<T>(
  chatId: string, operation: () => Promise<T>,
): Promise<T> {
  const previous = draftTransports.get(chatId) ?? Promise.resolve();
  let release!: () => void;
  const current = new Promise<void>((resolve) => { release = resolve; });
  const tail = previous.catch(() => undefined).then(() => current);
  draftTransports.set(chatId, tail);
  await previous.catch(() => undefined);
  try {
    return await operation();
  } finally {
    release();
    if (draftTransports.get(chatId) === tail) draftTransports.delete(chatId);
  }
}

async function persistTeamDraftIntent(
  chatId: string, context: DraftChatContext, kind: "update" | "delete",
): Promise<Chat | null> {
  if (!context.teamId || !isDraftChatContextCurrent(context)) return null;
  return chatDB.setTeamDraftPendingSync(chatId, context.teamId, kind,
    () => isDraftChatContextCurrent(context));
}

export async function deferTeamDraftSync(chatId: string, context: DraftChatContext): Promise<Chat | null> {
  return persistTeamDraftIntent(chatId, context, "update");
}

export async function deferTeamDraftDelete(chatId: string, context: DraftChatContext): Promise<Chat | null> {
  return persistTeamDraftIntent(chatId, context, "delete");
}

export async function clearTeamDraftIntent(
  chatId: string, context: DraftChatContext, kind: "update" | "delete",
  draft?: { cipher: string | null | undefined; version: number },
  clearedDraftVersion?: number,
): Promise<void> {
  if (!context.teamId || !isDraftChatContextCurrent(context)) return;
  await chatDB.setTeamDraftPendingSync(chatId, context.teamId, undefined,
    () => isDraftChatContextCurrent(context),
    { kind, ...(draft ? { cipher: draft.cipher, version: draft.version } : {}),
      clearedDraftVersion });
}

/** Retry a private precommit draft after ACK or authoritative Team metadata. */
export async function promoteDeferredTeamDraft(
  service: ChatSynchronizationService, chatId: string,
): Promise<void> {
  const active = get(activeTeamContext);
  if (!active.teamId) return;
  const deleteGeneration = draftDeleteGenerations.get(chatId) ?? 0;
  if (!isActiveTeamContext(active.teamId, active.epoch)) return;
  const chat = await chatDB.getRawChat(chatId);
  if (!isActiveTeamContext(active.teamId, active.epoch) ||
    (draftDeleteGenerations.get(chatId) ?? 0) !== deleteGeneration ||
    chat?.team_id !== active.teamId || chat.team_chat_pending_commit ||
    (chat.messages_v ?? 0) === 0 || !chat.team_draft_pending_sync) return;
  const context = { teamId: active.teamId, epoch: active.epoch, committed: true };
  if (chat.team_draft_pending_sync === "delete") {
    const editor = get(draftEditorUIState);
    if (chat.encrypted_draft_md || chat.encrypted_draft_preview ||
      (editor.currentChatId === chatId && editor.hasUnsavedChanges)) return;
    // The public sender checks this intent again while holding the transport.
    await service.sendDeleteDraft(chatId, context);
    return;
  }
  if (!chat.encrypted_draft_md || !(chat.draft_v ?? 0)) return;
  const draft = { cipher: chat.encrypted_draft_md, version: chat.draft_v };
  if ((draftDeleteGenerations.get(chatId) ?? 0) !== deleteGeneration) return;
  try {
    await service.sendUpdateDraft(chatId, draft.cipher,
      chat.encrypted_draft_preview, draft.version, context);
    if ((draftDeleteGenerations.get(chatId) ?? 0) === deleteGeneration) {
      await clearTeamDraftIntent(chatId, context, "update", draft);
    }
  } catch {
    if (!isDraftChatContextCurrent(context) ||
      (draftDeleteGenerations.get(chatId) ?? 0) !== deleteGeneration) return;
    const latest = await chatDB.getRawChat(chatId);
    if (!isDraftChatContextCurrent(context) || latest?.team_id !== context.teamId ||
      latest.team_draft_pending_sync !== "update" ||
      latest.encrypted_draft_md !== draft.cipher || (latest.draft_v ?? 0) !== draft.version) return;
    await service.queueOfflineChange({
      chat_id: chatId, team_id: active.teamId, type: "draft",
      value: draft.cipher,
      version_before_edit: Math.max(0, draft.version - 1),
    });
    await clearTeamDraftIntent(chatId, context, "update", draft);
  }
}

/** Keep draft traffic in the chat's workspace across asynchronous work. */
export async function resolveDraftChatContext(chatId: string): Promise<DraftChatContext> {
  const active = get(activeTeamContext);
  const chat = await chatDB.getRawChat(chatId);
  if (!isActiveTeamContext(active.teamId, active.epoch)) {
    throw new Error("Draft workspace changed");
  }
  if (!chat || (chat.team_id ?? null) !== active.teamId) {
    throw new Error("Draft chat does not belong to the active workspace");
  }
  const committed = (chat.messages_v ?? 0) > 0 && !(active.teamId && chat.team_chat_pending_commit);
  return { teamId: active.teamId, epoch: active.epoch, committed };
}

export function isDraftChatContextCurrent(context: DraftChatContext): boolean {
  return isActiveTeamContext(context.teamId, context.epoch);
}
