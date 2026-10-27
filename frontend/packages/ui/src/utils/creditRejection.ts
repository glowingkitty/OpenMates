/** Credit UI requires rejection evidence; waiting_for_user also serves ordinary prompts. */
type RejectionMessage = {
  message_id?: string;
  chat_id?: string;
  role: string;
  status?: string;
  content?: unknown;
  rejection_reason?: string | null;
  user_message_id?: string;
};

export function hasCreditRejectionEvidence(message: RejectionMessage | null | undefined): boolean {
  if (!message || (message.role !== 'system' && message.role !== 'assistant')) return false;
  if (message.rejection_reason === 'insufficient_credits') return true;
  if (message.role !== 'system') return false;
  const content = typeof message.content === 'string' ? message.content.toLowerCase() : '';
  return content.includes('insufficient credit') || content.includes('not enough credits') || content.includes('credits needed');
}

/** A user row inherits credit state only from its matching canonical rejection. */
export function isCreditRejection(message: RejectionMessage | null | undefined,
  related: readonly RejectionMessage[] = []): boolean {
  if (hasCreditRejectionEvidence(message)) return true;
  return message?.role === 'user' && message.status === 'waiting_for_user' && !!message.message_id &&
    related.some(candidate => candidate.chat_id === message.chat_id &&
      candidate.user_message_id === message.message_id && hasCreditRejectionEvidence(candidate));
}
