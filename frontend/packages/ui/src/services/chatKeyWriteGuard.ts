// frontend/packages/ui/src/services/chatKeyWriteGuard.ts
// Shared guard for client-side writes that persist chat-key-encrypted data.
// It prevents storing ciphertext produced with a raw key that does not match
// the chat's persisted key metadata.

import { notificationStore } from "../stores/notificationStore";
import { unwrapAnonymousChatKey } from "./anonymousChatKeyWrapping";
import { chatKeysEqual, encryptedChatKeyMatchesRawKey } from "./chatKeyConsistency";
import { chatDB } from "./db";
import { addCandidateKey } from "./db/chatCrudOperations";
import { decryptChatKeyWithMasterKey } from "./encryption/MetadataEncryptor";
import { computeKeyFingerprint } from "./encryption/ChatKeyManager";
import { rustWebCrypto } from "./rustCore/crypto/webCryptoClient";
import { rustEnsureChatKeySafeForWrite, type GuardReason } from "./rustCore/crypto/webCryptoFacades";

const CONFLICTING_KEYS_NOTICE =
  "We could not safely store this update because this chat has conflicting encryption keys. Please reload and try again.";
const KEY_NOT_VALIDATED_NOTICE =
  "We could not safely store this update because this chat key could not be validated. Please reload and try again.";

const GUARD_REFUSAL_LOG: Record<GuardReason, string> = {
  candidate_keys_pending: "chat has candidate/conflicting key(s) pending recovery",
  fingerprint_mismatch: "raw key fingerprint does not match stored chat key fingerprint",
  anonymous_key_unwrap_failed: "anonymous chat key could not be validated",
  anonymous_key_mismatch: "raw key does not match anonymous chat key",
  encrypted_key_missing: "no persisted encrypted_chat_key to validate against",
  persisted_key_unwrap_failed: "persisted chat key could not be validated",
  persisted_key_mismatch: "raw key does not match persisted encrypted_chat_key",
};

interface ChatKeyWriteGuardOptions {
  allowMissingEncryptedChatKey?: boolean;
  reportFailure?: boolean;
}

function recordChatKeyGuardFailure(
  reason: string,
  chat: { team_id?: string | null; candidate_encrypted_keys?: string[] | null } | null,
): void {
  if (typeof window === "undefined") return;
  (window as Window & { __openmatesLastChatKeyGuardDebug?: Record<string, unknown> })
    .__openmatesLastChatKeyGuardDebug = {
      reason,
      teamScoped: Boolean(chat?.team_id),
      candidateCount: chat?.candidate_encrypted_keys?.length ?? 0,
    };
}

function shouldReportFailure(options: ChatKeyWriteGuardOptions): boolean {
  return options.reportFailure !== false;
}

export async function ensureChatKeySafeForWrite(
  chatId: string,
  rawChatKey: Uint8Array,
  context: string,
  options: ChatKeyWriteGuardOptions = {},
): Promise<boolean> {
  const chat = await chatDB.getChat(chatId);
  const encryptedChatKey =
    chat?.encrypted_chat_key ?? (await chatDB.getEncryptedChatKey(chatId));
  const rawFingerprint = computeKeyFingerprint(rawChatKey);
  const reportFailure = shouldReportFailure(options);

  // Compile-time flag: default builds fold this to null and drop the Rust branch.
  const rust = import.meta.env.VITE_OPENMATES_RUST_CORE === "1" ? rustWebCrypto() : null;
  if (rust) {
    // Decisions in shared Rust (chat_key_policy); unwraps, candidate writes and
    // notices stay here so the observable behaviour is unchanged.
    return rustEnsureChatKeySafeForWrite(
      rust,
      {
        chatExists: Boolean(chat),
        candidateKeyCount: chat?.candidate_encrypted_keys?.length ?? 0,
        keyFingerprint: chat?.key_fingerprint || null,
        isAnonymous: Boolean(chat?.is_anonymous),
        teamScoped: Boolean(chat?.team_id),
        directVisibility: chat?.chat_visibility === "direct",
        encryptedChatKey: encryptedChatKey || null,
      },
      rawChatKey,
      Boolean(options.allowMissingEncryptedChatKey),
      {
        unwrapAnonymous: () => unwrapAnonymousChatKey(chat?.anonymous_encrypted_chat_key),
        unwrapPersisted: async (team) => {
          if (team && chat?.team_id) {
            const { unwrapTeamOrDirectChatKey } = await import("./directChatService");
            return unwrapTeamOrDirectChatKey(chat.team_id, chatId, encryptedChatKey!, chat.chat_visibility);
          }
          return decryptChatKeyWithMasterKey(encryptedChatKey!);
        },
        refuse: (reason, addCandidate, notice, error) => {
          recordChatKeyGuardFailure(reason, chat);
          if (addCandidate && encryptedChatKey) addCandidateKey(chatDB, chatId, encryptedChatKey).catch(() => {});
          if (reportFailure) {
            console.error(`[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: ${GUARD_REFUSAL_LOG[reason]}`, ...(error ? [error] : []));
            if (notice === "conflicting_keys") notificationStore.error(CONFLICTING_KEYS_NOTICE);
            else if (notice === "key_not_validated") notificationStore.error(KEY_NOT_VALIDATED_NOTICE);
          }
          return false;
        },
        allowUnverified: () => {
          console.warn(
            `[ChatKeyWriteGuard] Could not decrypt encrypted_chat_key while validating ${context} for ${chatId}; ` +
              `allowing write because hidden-chat/master-key fallback may own this wrapper.`,
          );
          return true;
        },
      },
    );
  }

  if (chat?.candidate_encrypted_keys?.length) {
    recordChatKeyGuardFailure("candidate_keys_pending", chat);
    if (reportFailure) {
      console.error(
        `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: chat has ` +
          `${chat.candidate_encrypted_keys.length} candidate/conflicting key(s) pending recovery`,
      );
      notificationStore.error(
        "We could not safely store this update because this chat has conflicting encryption keys. Please reload and try again.",
      );
    }
    return false;
  }

  if (chat?.key_fingerprint && chat.key_fingerprint !== rawFingerprint) {
    recordChatKeyGuardFailure("fingerprint_mismatch", chat);
    if (encryptedChatKey) addCandidateKey(chatDB, chatId, encryptedChatKey).catch(() => {});
    if (reportFailure) {
      console.error(
        `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: raw key fp=${rawFingerprint} ` +
          `does not match stored chat key fp=${chat.key_fingerprint}`,
      );
      notificationStore.error(
        "We could not safely store this update because this chat has conflicting encryption keys. Please reload and try again.",
      );
    }
    return false;
  }

  // Logged-out chats persist their key under a session wrapper, not the account
  // master-key wrapper. Validate that wrapper before accepting any local write.
  if (chat?.is_anonymous && !encryptedChatKey) {
    const anonymousKey = await unwrapAnonymousChatKey(chat.anonymous_encrypted_chat_key);
    if (!anonymousKey) {
      recordChatKeyGuardFailure("anonymous_key_unwrap_failed", chat);
      if (reportFailure) {
        console.error(
          `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: anonymous chat key could not be validated`,
        );
      }
      return false;
    }
    if (!chatKeysEqual(rawChatKey, anonymousKey)) {
      recordChatKeyGuardFailure("anonymous_key_mismatch", chat);
      if (reportFailure) {
        console.error(
          `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: raw key does not match anonymous chat key`,
        );
        notificationStore.error(
          "We could not safely store this update because this chat has conflicting encryption keys. Please reload and try again.",
        );
      }
      return false;
    }
    return true;
  }

  if (!encryptedChatKey) {
    if (options.allowMissingEncryptedChatKey && chat?.chat_visibility !== "direct") return true;
    recordChatKeyGuardFailure("encrypted_key_missing", chat);
    if (reportFailure) {
      console.error(
        `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: no persisted encrypted_chat_key to validate against`,
      );
    }
    return false;
  }

  let keyMatches: boolean | null;
  try {
    keyMatches = await encryptedChatKeyMatchesRawKey(
      encryptedChatKey,
      rawChatKey,
      chat?.team_id
        ? async (wrappedKey) => {
            // A private Team chat persists a participant envelope, never a
            // Team-wide wrapper. Keep the raw-key comparison for both formats.
            // Defer the service import to avoid the database bootstrap cycle.
            const { unwrapTeamOrDirectChatKey } = await import("./directChatService");
            return unwrapTeamOrDirectChatKey(
              chat.team_id!, chatId, wrappedKey, chat.chat_visibility,
            );
          }
        : async (wrappedKey) => {
            if (chat?.chat_visibility === "direct" || wrappedKey.startsWith("OMDM1.")) {
              throw new Error("Private chat has no Team context");
            }
            return decryptChatKeyWithMasterKey(wrappedKey);
          },
    );
  } catch (error) {
    recordChatKeyGuardFailure("persisted_key_unwrap_failed", chat);
    if (reportFailure) {
      console.error(
        `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: persisted chat key could not be validated`,
        error,
      );
      notificationStore.error(
        "We could not safely store this update because this chat key could not be validated. Please reload and try again.",
      );
    }
    return false;
  }

  if (keyMatches === false) {
    recordChatKeyGuardFailure("persisted_key_mismatch", chat);
    addCandidateKey(chatDB, chatId, encryptedChatKey).catch(() => {});
    if (reportFailure) {
      console.error(
        `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: raw key does not match persisted encrypted_chat_key`,
      );
      notificationStore.error(
        "We could not safely store this update because this chat has conflicting encryption keys. Please reload and try again.",
      );
    }
    return false;
  }

  if (keyMatches === null) {
    console.warn(
      `[ChatKeyWriteGuard] Could not decrypt encrypted_chat_key while validating ${context} for ${chatId}; ` +
        `allowing write because hidden-chat/master-key fallback may own this wrapper.`,
    );
  }

  return true;
}
