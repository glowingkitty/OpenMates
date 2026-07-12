/**
 * chatSyncServiceHandlersRecovery.ts - Sealed completion recovery handlers.
 *
 * Claims server-sealed completion jobs, decrypts them with chat-derived recovery
 * keys, and commits only chat-key-encrypted assistant messages. Plaintext remains
 * transient in browser memory and never crosses the durable server boundary.
 */
import type { ChatSynchronizationService } from "./chatSyncService";
import type { Message } from "../types/chat";
import {
  deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope,
  type ChatCompletionRecoveryEnvelope,
} from "../utils/chatCompletionRecovery";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { ensureChatKeySafeForWrite } from "./chatKeyWriteGuard";
import { webSocketService } from "./websocketService";

const CHAT_RECOVERY_PROTOCOL_VERSION = 1;
const CHAT_RECOVERY_EVENT_TIMEOUT_MS = 20_000;
const INITIAL_SYNC_POLL_MS = 100;
const RECOVERY_ERROR_CODES = new Set([
  "lease_conflict",
  "lease_tenure_exhausted",
  "recovery_job_expired",
  "recovery_job_not_found",
  "stale_lease",
  "terminal_identity_mismatch",
  "version_conflict",
]);
const recoveryJobsInProgress = new Set<string>();

interface AvailableRecoveryJob {
  job_id: string;
  chat_id: string;
  turn_id: string;
  assistant_message_id: string;
  chat_key_version: number;
}

function encodeRecoveryChatKey(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) binary += String.fromCharCode(bytes[index]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function waitForInitialSync(serviceInstance: ChatSynchronizationService): Promise<void> {
  const deadline = Date.now() + CHAT_RECOVERY_EVENT_TIMEOUT_MS;
  while (!serviceInstance.hasCompletedInitialSync_FOR_HANDLERS_ONLY) {
    if (Date.now() >= deadline) {
      throw new Error("Recovery job processing timed out waiting for initial chat sync.");
    }
    await new Promise((resolve) => window.setTimeout(resolve, INITIAL_SYNC_POLL_MS));
  }
}

function waitForRecoveryEvent(type: string, jobId: string): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error(`${type} timed out for recovery job ${jobId}`));
    }, CHAT_RECOVERY_EVENT_TIMEOUT_MS);
    const handleEvent = (payload: unknown) => {
      const event = payload as Record<string, unknown>;
      if (event.job_id !== jobId) return;
      cleanup();
      resolve(event);
    };
    const handleError = (payload: unknown) => {
      const event = payload as Record<string, unknown>;
      if (typeof event.code !== "string" || !RECOVERY_ERROR_CODES.has(event.code)) return;
      cleanup();
      reject(new Error(typeof event.message === "string" ? event.message : `${type} was rejected.`));
    };
    const cleanup = () => {
      window.clearTimeout(timeout);
      webSocketService.off(type, handleEvent);
      webSocketService.off("error", handleError);
    };
    webSocketService.on(type, handleEvent);
    webSocketService.on("error", handleError);
  });
}

export async function handleRecoveryJobsAvailableImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { jobs?: AvailableRecoveryJob[] },
): Promise<void> {
  await waitForInitialSync(serviceInstance);
  for (const job of payload.jobs ?? []) {
    if (!job.job_id || recoveryJobsInProgress.has(job.job_id)) continue;
    recoveryJobsInProgress.add(job.job_id);
    try {
      const existingMessage = await chatDB.getMessage(job.assistant_message_id);
      if (existingMessage?.status === "synced" || existingMessage?.status === "delivered") continue;

      const chat = await chatDB.getChat(job.chat_id);
      const chatKey = await chatKeyManager.getKey(job.chat_id);
      if (!chat?.user_id || !chatKey) continue;
      if (!(await ensureChatKeySafeForWrite(job.chat_id, chatKey, "completion recovery"))) continue;

      const claimed = waitForRecoveryEvent("recovery_job_claimed", job.job_id);
      await webSocketService.sendMessage("recovery_job_claim", {
        protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION,
        job_id: job.job_id,
      });
      const claim = await claimed;
      if (
        claim.state !== "LEASED" ||
        typeof claim.lease_token !== "string" ||
        typeof claim.lease_generation !== "number" ||
        typeof claim.sealed_payload !== "string" ||
        claim.chat_id !== job.chat_id ||
        claim.turn_id !== job.turn_id ||
        claim.assistant_message_id !== job.assistant_message_id ||
        claim.chat_key_version !== job.chat_key_version
      ) {
        throw new Error(`Recovery job ${job.job_id} returned invalid lease or identity data.`);
      }

      const recoveryKeypair = await deriveChatCompletionRecoveryKeypair(
        encodeRecoveryChatKey(chatKey),
        job.chat_id,
        job.chat_key_version,
      );
      const plaintext = await openChatCompletionRecoveryEnvelope(
        JSON.parse(claim.sealed_payload) as ChatCompletionRecoveryEnvelope,
        {
          recoveryPrivateKey: recoveryKeypair.privateKey,
          ownerId: chat.user_id,
          chatId: job.chat_id,
          turnId: job.turn_id,
          jobId: job.job_id,
          assistantMessageId: job.assistant_message_id,
          keyVersion: job.chat_key_version,
        },
      );
      const recovered = JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(plaintext),
      ) as Record<string, unknown>;
      if (
        recovered.job_id !== job.job_id ||
        recovered.chat_id !== job.chat_id ||
        recovered.turn_id !== job.turn_id ||
        recovered.assistant_message_id !== job.assistant_message_id ||
        recovered.key_version !== job.chat_key_version ||
        typeof recovered.content !== "string" ||
        (recovered.category !== null && typeof recovered.category !== "string") ||
        (recovered.model_name !== null && typeof recovered.model_name !== "string")
      ) {
        throw new Error(`Recovery job ${job.job_id} plaintext identity did not match its lease.`);
      }

      const now = Math.floor(Date.now() / 1000);
      const aiMessage = {
        message_id: job.assistant_message_id,
        chat_id: job.chat_id,
        role: "assistant",
        content: recovered.content,
        category: recovered.category ?? undefined,
        model_name: recovered.model_name ?? undefined,
        status: "synced",
        created_at: now,
      } as Message;
      const encryptedFields = await chatDB.getEncryptedFields(aiMessage, job.chat_id);
      const persisted = waitForRecoveryEvent("recovery_job_persisted", job.job_id);
      await webSocketService.sendMessage("recovery_job_persist", {
        protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION,
        job_id: job.job_id,
        lease_token: claim.lease_token,
        lease_generation: claim.lease_generation,
        expected_messages_v: chat.messages_v,
        encrypted_assistant_message: {
          client_message_id: job.assistant_message_id,
          chat_id: job.chat_id,
          role: "assistant",
          encrypted_content: encryptedFields.encrypted_content,
          encrypted_sender_name: encryptedFields.encrypted_sender_name,
          encrypted_category: encryptedFields.encrypted_category,
          encrypted_model_name: encryptedFields.encrypted_model_name,
          created_at: now,
          updated_at: now,
        },
      });
      const persistedResult = await persisted;
      if (
        persistedResult.state !== "TERMINAL" ||
        (persistedResult.committed_messages_v !== undefined &&
          (typeof persistedResult.committed_messages_v !== "number" ||
            !Number.isSafeInteger(persistedResult.committed_messages_v)))
      ) {
        throw new Error(`Recovery job ${job.job_id} persistence acknowledgement was invalid.`);
      }

      await chatDB.saveMessage(aiMessage);
      const updatedChat = {
        ...chat,
        messages_v:
          typeof persistedResult.committed_messages_v === "number"
            ? persistedResult.committed_messages_v
            : chat.messages_v + 1,
        last_edited_overall_timestamp: now,
        updated_at: now,
      };
      await chatDB.updateChat(updatedChat);
      serviceInstance.dispatchEvent(
        new CustomEvent("chatUpdated", {
          detail: {
            chat_id: job.chat_id,
            chat: updatedChat,
            newMessage: aiMessage,
            type: "recovery_job_persisted",
            messagesUpdated: true,
          },
        }),
      );
    } catch (error) {
      console.error(`[ChatSyncService:Recovery] Failed recovery job ${job.job_id}:`, error);
    } finally {
      recoveryJobsInProgress.delete(job.job_id);
    }
  }
}
