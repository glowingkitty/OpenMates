/** Keep an accepted response attached to its triggering user while later follow-ups arrive. */
export function responseUserMessageId(
  activeTaskUserMessageId: string | null | undefined,
  acceptedFeedbackUserMessageId: string | null | undefined,
  messages: readonly { role: string; status?: string; message_id: string }[],
): string | null {
  if (activeTaskUserMessageId) return activeTaskUserMessageId;
  if (acceptedFeedbackUserMessageId) return acceptedFeedbackUserMessageId;
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index];
    if (message.role === 'user' && message.status !== 'queued') return message.message_id;
  }
  return null;
}
