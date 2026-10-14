import { createHash } from "node:crypto";
import type { AvailableRecoveryOutputFrame } from "./ws.js";
import type { SyncCache } from "./storage.js";

export const RECOVERY_FAILURE_RETRY_DELAY_MS = 5_000;
const MAX_FAILURES = 512;
// Existing discovery bounds: 100 pages ×100 records ×three metadata passes.
export const MAX_RECOVERY_OPERATION_FAILURES = 30_000;
const digest = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");

export function recoveryOutputIdentity(output: AvailableRecoveryOutputFrame): string {
  return JSON.stringify([
    output.root_chat_id, output.target_chat_id, output.turn_id, output.subject_id,
    output.output_kind, output.output_version, output.chat_key_version,
    output.message_role ?? null, output.root_hashed_team_id ?? null,
  ]);
}

/** Local ciphertext/key metadata only; no probe or decrypted content is needed. */
export function recoveryReadinessSignature(cache: SyncCache, output: AvailableRecoveryOutputFrame): string {
  const head = cache.embeds?.find(row => (row.embed_id ?? row.id) === output.subject_id);
  const subjects = new Set<string>();
  if (typeof output.subject_id === "string") subjects.add(output.subject_id);
  if (typeof head?.parent_embed_id === "string") subjects.add(head.parent_embed_id);
  const hashes = new Set([...subjects].filter((id): id is string => typeof id === "string").map(id => createHash("sha256").update(id).digest("hex")));
  const heads = (cache.embeds ?? []).filter(row => subjects.has(String(row.embed_id ?? row.id)))
    .map(row => [row.embed_id ?? row.id, row.parent_embed_id, row.status, row.version_number,
      row.encrypted_content, row.encrypted_type]);
  const keys = (cache.embedKeys ?? []).filter(row => hashes.has(String(row.hashed_embed_id)))
    .map(row => [row.hashed_embed_id, row.hashed_chat_id, row.hashed_user_id, row.key_type, row.encrypted_embed_key]);
  const chats = (cache.chats ?? []).filter(row => [output.root_chat_id, output.target_chat_id].includes(String(row.details.id)))
    .map(row => [row.details.id, row.details.encrypted_chat_key, row.details.chat_key_version]);
  const canonicalOrder = (rows: unknown[][]) => rows.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
  const chatHashes = new Set([output.root_chat_id, output.target_chat_id]
    .filter((id): id is string => typeof id === "string").map(id => createHash("sha256").update(id).digest("hex")));
  const wrappers = (cache.chatKeyWrappers ?? []).filter(row => chatHashes.has(String(row.hashed_chat_id)))
    .map(row => [row.hashed_chat_id, row.hashed_user_id, row.hashed_team_id, row.key_type,
      row.chat_key_version, row.key_version, row.encrypted_chat_key]);
  return digest([canonicalOrder(heads), canonicalOrder(keys), canonicalOrder(chats), canonicalOrder(wrappers)]);
}

type FailedAttempt = { readiness: string; progress: number; retryAfter: number };
export type RecoveryRetryOperation = { failed: Map<string, FailedAttempt> };

/** Volatile, owner/Team-scoped retry state. A new CLI process starts fresh. */
export class RecoveryFailureRetry {
  private failures = new Map<string, FailedAttempt>();
  private progress = new Map<string, number>();
  private nextProgress = 0;

  beginOperation(): RecoveryRetryOperation { return { failed: new Map() }; }

  private keys(scope: string, output: AvailableRecoveryOutputFrame) {
    return {
      identity: digest([scope, output.record_id, recoveryOutputIdentity(output)]),
      // Any verified persistence in the same source chat/key generation may
      // create the head, chat key or parent wrapper a failed leaf needs.
      related: digest([scope, output.root_hashed_team_id ?? null, output.target_chat_id, output.chat_key_version]),
    };
  }

  shouldDefer(scope: string, output: AvailableRecoveryOutputFrame, readiness: string, operation: RecoveryRetryOperation): boolean {
    const keys = this.keys(scope, output), progress = this.progress.get(keys.related) ?? 0;
    const sameOperation = operation.failed.get(keys.identity);
    // Do not evict prior failures and replay them within the same operation.
    // Overflow remains pending; the next operation has a fresh bounded map.
    if (!sameOperation && operation.failed.size >= MAX_RECOVERY_OPERATION_FAILURES) return true;
    if (sameOperation?.readiness === readiness && sameOperation.progress === progress) return true;
    const recent = this.failures.get(keys.identity);
    return recent?.readiness === readiness && recent.progress === progress && Date.now() < recent.retryAfter;
  }

  failed(scope: string, output: AvailableRecoveryOutputFrame, readiness: string, operation: RecoveryRetryOperation): void {
    const keys = this.keys(scope, output);
    const failure = { readiness, progress: this.progress.get(keys.related) ?? 0,
      retryAfter: Date.now() + RECOVERY_FAILURE_RETRY_DELAY_MS };
    if (operation.failed.has(keys.identity) || operation.failed.size < MAX_RECOVERY_OPERATION_FAILURES) {
      operation.failed.set(keys.identity, failure);
    }
    this.failures.delete(keys.identity);
    this.failures.set(keys.identity, failure);
    while (this.failures.size > MAX_FAILURES) this.failures.delete(this.failures.keys().next().value!);
  }

  succeeded(scope: string, output: AvailableRecoveryOutputFrame, operation: RecoveryRetryOperation): void {
    const keys = this.keys(scope, output);
    this.failures.delete(keys.identity); operation.failed.delete(keys.identity);
    this.progress.delete(keys.related);
    this.progress.set(keys.related, ++this.nextProgress);
    // Bound the auxiliary metadata without discarding failure identities.
    if (this.progress.size > MAX_FAILURES) this.progress.delete(this.progress.keys().next().value!);
  }
}
