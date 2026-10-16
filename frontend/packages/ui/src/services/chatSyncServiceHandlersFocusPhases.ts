// Persist only authoritative live phase updates; rendering history has no side effects.
import type { ChatSynchronizationService } from "./chatSyncService";
import type { FocusPhaseState } from "../types/focusPhases";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { encryptWithChatKey, decryptWithChatKey } from "./encryption/MessageEncryptor";
import { ensureChatKeySafeForWrite } from "./chatKeyWriteGuard";
import { webSocketService } from "./websocketService";
import { chatMetadataCache } from "./chatMetadataCache";

// Serialize concurrent events for the same chat so an older encryption cannot win.
const queues = new Map<string, Promise<void>>();
export function handleFocusPhasesUpdated(service: ChatSynchronizationService,
  payload: { chat_id: string; states: Record<string, FocusPhaseState> }): Promise<void> {
  const previous = queues.get(payload.chat_id) ?? Promise.resolve();
  const next = previous.catch(() => {}).then(() => apply(service, payload));
  queues.set(payload.chat_id, next);
  void next.finally(() => { if (queues.get(payload.chat_id) === next) queues.delete(payload.chat_id); }).catch(() => {});
  return next;
}
async function apply(service: ChatSynchronizationService,
  payload: { chat_id: string; states: Record<string, FocusPhaseState> }): Promise<void> {
  if (!payload.chat_id || !payload.states || typeof payload.states !== "object") return;
  const chat = await chatDB.getChat(payload.chat_id);
  const key = await chatKeyManager.getKey(payload.chat_id);
  if (!chat || !key || !(await ensureChatKeySafeForWrite(payload.chat_id, key, "focus phase progress"))) return;
  const savedText = chat.encrypted_focus_phase_state ? await decryptWithChatKey(chat.encrypted_focus_phase_state, key) : null;
  const saved: Record<string, FocusPhaseState> = savedText ? JSON.parse(savedText) : {};
  const states = { ...payload.states };
  for (const [focusId, state] of Object.entries(states)) {
    if (state.schema_version !== 1 || state.chat_id !== payload.chat_id || state.focus_id !== focusId
        || !Number.isSafeInteger(state.version) || state.version < 0 || !Array.isArray(state.transitions)
        || state.transitions.length > 32) throw new Error("Invalid focus phase state");
    if (saved[focusId]?.run_id === state.run_id && saved[focusId].version > state.version) states[focusId] = saved[focusId];
  }
  const encrypted = await encryptWithChatKey(JSON.stringify(states), key);
  chat.encrypted_focus_phase_state = encrypted;
  await chatDB.updateChat(chat);
  chatMetadataCache.invalidateChat(payload.chat_id);
  await webSocketService.sendMessage("encrypted_chat_metadata", {
    chat_id: payload.chat_id, team_id: chat.team_id ?? undefined,
    encrypted_focus_phase_state: encrypted,
  });
  for (const state of Object.values(states)) for (const event of state.transitions) {
    if (event.chat_id !== payload.chat_id || event.focus_id !== state.focus_id || !event.event_id) continue;
    // Same UUID on every device gives server/storage idempotency.
    if (await chatDB.getMessage(event.event_id)) continue;
    const content = JSON.stringify(event);
    const encryptedContent = await encryptWithChatKey(content, key);
    const message = { message_id: event.event_id, chat_id: payload.chat_id, role: "system" as const,
      content, encrypted_content: encryptedContent, created_at: event.created_at, status: "sending" as const };
    await chatDB.saveMessage(message);
    await webSocketService.sendMessage("chat_system_message_added", { chat_id: payload.chat_id,
      message: { ...message, content: undefined, status: "synced" } });
    const synced = { ...message, status: "synced" as const };
    await chatDB.saveMessage(synced);
    service.dispatchEvent(new CustomEvent("chatUpdated", { detail: { chat_id: payload.chat_id,
      type: "system_message_added", newMessage: synced } }));
  }
}
