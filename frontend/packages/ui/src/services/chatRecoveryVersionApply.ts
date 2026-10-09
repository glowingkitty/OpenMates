import type { Chat } from '../types/chat';

/** Preserve a newer local authoritative chat snapshot while applying an older
 * recovered terminal ACK. The ACK's exact version remains the send fence. */
export function chatAfterRecoveredReply(
  current: Chat | null, baseline: Chat, committedVersion: number, now: number,
): Chat {
  const latest = current ?? baseline;
  if (latest.messages_v > committedVersion) return latest;
  return {
    ...latest,
    messages_v: committedVersion,
    last_edited_overall_timestamp: Math.max(latest.last_edited_overall_timestamp, now),
    updated_at: Math.max(latest.updated_at, now),
  };
}
