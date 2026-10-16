/** Optional metadata owns a bounded subscription after required reply persistence. */
import type { OpenMatesWsClient } from './ws.js';

export type CliTurnMetadata = {
  chatId: string; turnId: string; userMessageId: string;
  followUpSuggestions: string[]; newChatSuggestions: string[]; suggestedFollowupMessage: string | null;
  chatSummary: string | null; chatTags: string[]; updatedChatTitle: string | null;
  sourceTitleVersion: number | null; sourceMetadataVersion: number | null;
};

const strings = (value: unknown, limit: number): string[] => Array.isArray(value)
  ? value.filter((item): item is string => typeof item === 'string' && !!item.trim()).slice(0, limit) : [];
const text = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value.trim() : null;
const version = (value: unknown): number | null => Number.isSafeInteger(value) && (value as number) >= 0 ? value as number : null;

export function observeOwnedTurnMetadata(options: {
  ws: OpenMatesWsClient; chatId: string; turnId: string; userMessageId: string;
  ownerCurrent: () => boolean;
  persist: (metadata: CliTurnMetadata) => Promise<void>;
  onMetadata?: (metadata: CliTurnMetadata) => void;
  onReleased?: () => void;
  retentionMs?: number;
  closeAfterMetadata?: boolean;
}): { handOff: (suggestedFollowupMessage?: string | null, persistHeader?: () => Promise<void>) => boolean; stop: () => void } {
  let ready = false, stopped = false, taskId: string | null = null;
  let unsupportedDelivered = false;
  let pending: CliTurnMetadata | null = null;
  let suggestedFollowupMessage: string | null = null;
  let lastMetadataVersion = -1;
  let lastIdentity: string | null = null;
  let work = Promise.resolve();
  let timer: ReturnType<typeof setTimeout> | null = null;
  const removes: Array<() => void> = [];
  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (timer) clearTimeout(timer);
    pending = null;
    removes.forEach(remove => remove());
    options.onReleased?.();
  };
  const flush = () => {
    if (!ready || !pending || stopped) return;
    const metadata = pending; pending = null;
    work = work.then(async () => {
      if (stopped || !options.ownerCurrent() || !options.ws.isOpen()) { stop(); return; }
      // Required completion has already settled. Failure here preserves the
      // reply and leaves metadata recoverable; it cannot become a send failure.
      await options.persist(metadata);
      if (!stopped && options.ownerCurrent()) options.onMetadata?.(metadata);
      if (options.closeAfterMetadata) stop();
    }).catch(() => { /* Optional metadata remains a separate milestone. */ });
  };
  removes.push(options.ws.onMessageType<Record<string, unknown>>('ai_typing_started', frame => {
    if (frame.chat_id !== options.chatId || (frame.user_message_id !== options.userMessageId
      && frame.userMessageId !== options.userMessageId)) return;
    taskId = text(frame.task_id) ?? text(frame.message_id);
  }));
  const receive = (frame: Record<string, unknown>) => {
    if (stopped || !options.ownerCurrent()) { stop(); return; }
    if (!frame || frame.chat_id !== options.chatId) return;
    if ((frame.turn_id !== undefined && frame.turn_id !== options.turnId)
      || (frame.user_message_id !== undefined && frame.user_message_id !== options.userMessageId)) return;
    // Old servers carry task_id. A chat-only broadcast cannot distinguish a
    // late prior turn from a subsequent request, so it must not update this UI.
    if (frame.turn_id !== options.turnId && frame.user_message_id !== options.userMessageId
      && (!taskId || frame.task_id !== taskId)) {
      if (frame.turn_id === undefined && frame.user_message_id === undefined && frame.task_id === undefined) {
        unsupportedDelivered = true;
        // A legacy chat-only delivery cannot safely update another turn. Its
        // arrival does tell us that retaining this transport longer is useless.
        if (ready) work = work.then(stop);
      }
      return;
    }
    const metadataVersion = version(frame.source_metadata_v);
    if (metadataVersion !== null && metadataVersion < lastMetadataVersion) return;
    const identity = JSON.stringify(frame);
    if (identity === lastIdentity) return;
    lastIdentity = identity;
    lastMetadataVersion = Math.max(lastMetadataVersion, metadataVersion ?? -1);
    pending = { chatId: options.chatId, turnId: options.turnId, userMessageId: options.userMessageId,
      followUpSuggestions: strings(frame.follow_up_request_suggestions, 18),
      newChatSuggestions: strings(frame.new_chat_request_suggestions, 6), suggestedFollowupMessage,
      chatSummary: text(frame.chat_summary), chatTags: strings(frame.chat_tags, 10),
      updatedChatTitle: text(frame.updated_chat_title), sourceTitleVersion: version(frame.source_title_v),
      sourceMetadataVersion: metadataVersion };
    flush();
  };
  removes.push(options.ws.onMessageType<Record<string, unknown>>('post_processing_completed', receive));
  removes.push(options.ws.onMessageType<Record<string, unknown>>('post_processing_metadata', receive));
  removes.push(options.ws.onClose(stop));
  return { stop, handOff(suggestion, persistHeader) {
    if (stopped) return false;
    if (persistHeader) work = work.then(async () => {
      if (!stopped && options.ownerCurrent() && options.ws.isOpen()) await persistHeader();
    }).catch(() => { /* A missing optional header does not delay the reply. */ });
    ready = true;
    suggestedFollowupMessage = suggestion ?? null;
    if (pending) pending.suggestedFollowupMessage = suggestedFollowupMessage;
    flush();
    timer = setTimeout(stop, options.retentionMs ?? 120_000);
    timer.unref?.();
    if (unsupportedDelivered && !pending) work = work.then(stop);
    return true;
  } };
}
