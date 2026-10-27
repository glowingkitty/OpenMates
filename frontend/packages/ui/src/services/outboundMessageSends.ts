/** Coalesce a local send and its journal recovery on the same authenticated socket. */
export class OutboundMessageSends {
  private readonly pending = new Map<string, {
    scope: string;
    content: string;
    canonicalContent?: string;
    sent: Promise<void>;
  }>();

  clear(): void { this.pending.clear(); }

  run(
    scope: string,
    messageId: string,
    content: string,
    send: (holdUntil: (completion: Promise<void>, canonicalContent?: string) => void) => Promise<void>,
  ): Promise<void> {
    // Old account/Team/socket completions must never suppress the new owner.
    for (const [key, entry] of this.pending) {
      if (entry.scope !== scope) this.pending.delete(key);
    }
    const existing = this.pending.get(messageId);
    if (existing) {
      if (existing.content === content || existing.canonicalContent === content) return existing.sent;
      // Preparation may canonicalize timestamps or privacy placeholders. Only
      // the trusted sender can register that validated representation; wait for
      // it rather than accepting arbitrary edits under a reused message ID.
      return existing.sent.then(() => {
        if (existing.content !== content && existing.canonicalContent !== content) {
          throw new Error('An active message send cannot change its immutable content.');
        }
      });
    }
    let resolve!: () => void;
    let reject!: (error: unknown) => void;
    const sent = new Promise<void>((done, failed) => { resolve = done; reject = failed; });
    const entry: { scope: string; content: string; canonicalContent?: string; sent: Promise<void> } = { scope, content, sent };
    this.pending.set(messageId, entry); // Reserve before preparation can await.
    let completion: Promise<void> | undefined;
    void (async () => {
      try {
        await send((pending, canonicalContent) => {
          completion = pending;
          entry.canonicalContent = canonicalContent;
        });
        resolve(); // Sending remains responsive while context ACKs are pending.
        await completion;
      } catch (error) {
        reject(error);
      } finally {
        if (this.pending.get(messageId) === entry) this.pending.delete(messageId);
      }
    })();
    return sent;
  }
}
