/** Capabilities belong to one authenticated WebSocket connection. */
export class ServerCapabilityGate {
  private capabilities: ReadonlySet<string> | null = null;

  reset(): void {
    this.capabilities = null;
  }

  accept(payload: unknown): void {
    const value = payload as { capabilities?: unknown } | null;
    if (!value || !Array.isArray(value.capabilities) ||
      value.capabilities.some((capability) => typeof capability !== 'string')) {
      this.capabilities = null;
      return;
    }
    this.capabilities = new Set(value.capabilities);
  }

  supportsImmediateChatAdmission(): boolean {
    return this.capabilities?.has('chat_turn_admit_v1') === true
      && this.capabilities.has('chat_turn_context_v1');
  }
}

export class PendingAdmissionCompatibilityError extends Error {
  constructor() {
    super('Pending chat admission needs a compatible server connection for exact-ID retry.');
  }
}
