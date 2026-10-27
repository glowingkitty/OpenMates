/** Bound read telemetry across animation frames without retaining message content. */
export interface VisibleReceiptScope {
  ownerId: string;
  chatId: string;
  epoch: number;
  connection: object | null;
}

const RECEIPT_RECHECK_MS = 30_000;
const MAX_RECENT_RECEIPTS = 512;

export class VisibleMessageReceipts {
  private scope: VisibleReceiptScope | null = null;
  private receipts = new Map<string, { sentAt: number; pending?: Promise<boolean> }>();

  async report(scope: VisibleReceiptScope, messageId: string, send: () => Promise<void>): Promise<boolean> {
    if (!scope.ownerId || !scope.connection) return false;
    if (!this.scope || this.scope.ownerId !== scope.ownerId || this.scope.chatId !== scope.chatId
      || this.scope.epoch !== scope.epoch || this.scope.connection !== scope.connection) {
      this.scope = scope;
      this.receipts = new Map();
    }
    const receipts = this.receipts;
    const previous = receipts.get(messageId);
    if (previous?.pending) return previous.pending;
    if (previous && Date.now() - previous.sentAt < RECEIPT_RECHECK_MS) return true;
    while (receipts.size >= MAX_RECENT_RECEIPTS) receipts.delete(receipts.keys().next().value!);
    const entry = { sentAt: 0, pending: undefined as Promise<boolean> | undefined };
    entry.pending = Promise.resolve().then(send).then(() => {
      entry.sentAt = Date.now();
      entry.pending = undefined;
      return true;
    }, () => {
      // A failed receipt remains eligible on the next visible-frame callback.
      if (receipts.get(messageId) === entry) receipts.delete(messageId);
      return false;
    });
    receipts.set(messageId, entry);
    return entry.pending;
  }
}
