/**
 * Holds timestamps from authenticated recovery-v1 final stream events.
 * Keys include chat, assistant, recovery job and turn identities.
 * Recovery discovery can precede the final marker, so callers may wait briefly.
 * Entries stay in memory only and expire after ten minutes.
 * Missing metadata falls back to ordinary cold recovery persistence.
 */
type RecoveryFinal = {
  chat_id: string;
  message_id: string;
  user_message_id: string;
  recovery_job_id?: string | null;
  recovery_turn_id?: string | null;
  recovery_protocol_version?: number | null;
  created_at?: number;
  is_final_chunk?: boolean;
};

const finalTimestamps = new Map<string, { createdAt: number; receivedAt: number }>();
const waiters = new Map<string, Set<(createdAt: number | null) => void>>();
const MAX_FINAL_TIMESTAMPS = 128;
const MAX_AGE_MS = 10 * 60_000;
const MAX_WAITERS = 128;
const FINAL_METADATA_WAIT_MS = 2_000;

function key(chatId: string, messageId: string, jobId: string, turnId: string): string {
  return JSON.stringify([chatId, messageId, jobId, turnId]);
}

export function recordRecoveryFinalTimestamp(event: RecoveryFinal): void {
  if (event.is_final_chunk !== true || event.recovery_protocol_version !== 1
    || !event.chat_id || !event.message_id || !event.user_message_id
    || !event.recovery_job_id || !event.recovery_turn_id
    || !Number.isSafeInteger(event.created_at) || (event.created_at as number) <= 0) return;
  const receivedAt = Date.now();
  for (const [identity, value] of finalTimestamps) {
    if (receivedAt - value.receivedAt > MAX_AGE_MS) finalTimestamps.delete(identity);
  }
  const identity = key(event.chat_id, event.message_id, event.recovery_job_id, event.recovery_turn_id);
  finalTimestamps.set(
    identity,
    { createdAt: event.created_at as number, receivedAt },
  );
  for (const resolve of waiters.get(identity) ?? []) resolve(event.created_at as number);
  waiters.delete(identity);
  while (finalTimestamps.size > MAX_FINAL_TIMESTAMPS) {
    finalTimestamps.delete(finalTimestamps.keys().next().value!);
  }
}

export function recoveryFinalTimestamp(
  chatId: string, messageId: string, jobId: string, turnId: string,
): number | null {
  const value = finalTimestamps.get(key(chatId, messageId, jobId, turnId));
  return value && Date.now() - value.receivedAt <= MAX_AGE_MS ? value.createdAt : null;
}

export function waitForRecoveryFinalTimestamp(
  chatId: string, messageId: string, jobId: string, turnId: string,
): Promise<number | null> {
  const existing = recoveryFinalTimestamp(chatId, messageId, jobId, turnId);
  if (existing !== null) return Promise.resolve(existing);
  if ([...waiters.values()].reduce((sum, group) => sum + group.size, 0) >= MAX_WAITERS) {
    return Promise.resolve(null);
  }
  const identity = key(chatId, messageId, jobId, turnId);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (createdAt: number | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const group = waiters.get(identity);
      group?.delete(finish);
      if (group?.size === 0) waiters.delete(identity);
      resolve(createdAt);
    };
    const timer = setTimeout(() => finish(null), FINAL_METADATA_WAIT_MS);
    const group = waiters.get(identity) ?? new Set<(createdAt: number | null) => void>();
    group.add(finish);
    waiters.set(identity, group);
  });
}

export function clearRecoveryFinalTimestamps(): void {
  finalTimestamps.clear();
  for (const group of waiters.values()) for (const resolve of group) resolve(null);
  waiters.clear();
}
