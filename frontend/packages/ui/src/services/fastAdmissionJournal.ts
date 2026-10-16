/** Completion fence for an admitted turn that still needs private client context. */
export interface FastAdmissionIdentity {
  chatId: string;
  messageId: string;
  turnId: string;
  requestId: string;
  committedMessagesVersion: number;
}

export class FastAdmissionJournalGate {
  private confirmed = false;
  private routingAccepted = false;
  private detailsAccepted = false;
  private attempt = 0;
  private rejected = false;
  private onRejected?: () => void;

  constructor(private readonly identity: FastAdmissionIdentity) {}

  beginAttempt(onRejected?: () => void): () => boolean {
    const attempt = ++this.attempt;
    this.rejected = false;
    this.onRejected = onRejected;
    return () => this.attempt === attempt && !this.rejected;
  }

  acceptConfirmation(value: unknown): boolean {
    const event = value as Record<string, unknown> | null;
    if (event?.chat_id === this.identity.chatId &&
      event.message_id === this.identity.messageId &&
      event.new_messages_v === this.identity.committedMessagesVersion) {
      this.confirmed = true;
    }
    return this.complete;
  }

  acceptContextAck(value: unknown): boolean {
    const event = value as Record<string, unknown> | null;
    if (event?.chat_id !== this.identity.chatId ||
      event.message_id !== this.identity.messageId ||
      event.turn_id !== this.identity.turnId ||
      event.request_id !== this.identity.requestId ||
      !['accepted', 'duplicate'].includes(String(event.status))) return this.complete;
    if (event.phase === 'routing') this.routingAccepted = true;
    if (event.phase === 'details') this.detailsAccepted = true;
    return this.complete;
  }

  isRejectedContextAck(value: unknown): boolean {
    const event = value as Record<string, unknown> | null;
    return event?.chat_id === this.identity.chatId &&
      event.message_id === this.identity.messageId &&
      event.turn_id === this.identity.turnId &&
      event.request_id === this.identity.requestId &&
      (event.phase === 'routing' || event.phase === 'details') &&
      event.status === 'rejected';
  }

  rejectContextAck(value: unknown): boolean {
    if (!this.isRejectedContextAck(value)) return false;
    if (!this.rejected) {
      this.rejected = true;
      this.onRejected?.();
    }
    return true;
  }

  get complete(): boolean {
    return this.confirmed && this.routingAccepted && this.detailsAccepted;
  }
}

/** Retry only an exact pending admission; validation of the sealed payload follows. */
export function isRetainedFastAdmissionSnapshot(
  snapshot: Record<string, unknown>, chatId: string, messageId: string,
): boolean {
  const payload = snapshot.payload as Record<string, unknown> | undefined;
  const request = payload?.inference_request as Record<string, unknown> | undefined;
  return snapshot.chat_id === chatId && snapshot.message_id === messageId
    && payload?.chat_id === chatId && payload.message_id === messageId
    && request?.chat_id === chatId && request?.client_context_pending === true
    && typeof request.client_context_request_id === 'string'
    && request.client_context_request_id.length > 0;
}
