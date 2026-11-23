/**
 * Web shell of the E2B upload consent (assertion code-run.e2b.upload-consent).
 * The client core builds and encrypts the request/response system messages and
 * the answer frame (`e2bConsent` Worker unit); this file only sends the returned
 * frames on the main socket and stores the message in the chat store.
 */
import type { ChatSynchronizationService } from "./chatSyncService";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import {
  e2bConsentAnswerStep,
  e2bConsentRequestStep,
  recordE2bConsentUpdate,
} from "./rustCore/e2bConsent/e2bConsentClient";
import type { E2bConsentChoiceWire, E2bConsentStep } from "./rustCore/e2bConsent/e2bConsentProtocol";

async function applyStep(service: ChatSynchronizationService, chatId: string, step: E2bConsentStep): Promise<void> {
  const { webSocketService } = await import("./websocketService");
  const stored = { ...step.message, status: "sending" as const };
  await chatDB.saveMessage(stored);
  for (const frame of step.frames) await webSocketService.sendMessage(frame.name, frame.payload);
  const synced = { ...stored, status: "synced" as const };
  await chatDB.saveMessage(synced);
  service.dispatchEvent(
    new CustomEvent("chatUpdated", {
      detail: { chat_id: chatId, type: "system_message_added", newMessage: synced },
    }),
  );
}

async function chatKeyOf(chatId: string): Promise<Uint8Array> {
  const key = await chatKeyManager.getKey(chatId);
  if (!key) throw new Error(`No chat key found for chat ${chatId}`);
  return key;
}

/** `request_e2b_upload_consent {request_id, chat_id, version}`: persist the request card message. */
export async function handleRequestE2bUploadConsentImpl(
  service: ChatSynchronizationService,
  payload: { request_id: string; chat_id: string; version: number },
): Promise<void> {
  const step = await e2bConsentRequestStep(payload, await chatKeyOf(payload.chat_id));
  await applyStep(service, payload.chat_id, step);
}

/** The user's answer to the request card: send the answer frame and persist the response. */
export async function answerE2bUploadConsent(
  service: ChatSynchronizationService,
  chatId: string,
  requestId: string,
  choice: E2bConsentChoiceWire,
): Promise<void> {
  const step = await e2bConsentAnswerStep(chatId, requestId, choice, await chatKeyOf(chatId));
  await applyStep(service, chatId, step);
}

/** `e2b_upload_consent_updated`: keep only the decision in the store the gating code reads. */
export function handleE2bUploadConsentUpdatedImpl(
  payload: { decision?: unknown; decided_at?: unknown; version?: unknown },
): void {
  recordE2bConsentUpdate(payload);
}
