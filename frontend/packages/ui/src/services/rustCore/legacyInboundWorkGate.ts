/** Per-service platform callback lifetime. No Rust admission or sync policy. */
type Handler<T> = (payload: T) => void | Promise<void>;
interface Socket {
  on<T>(type: string, handler: Handler<T>): void;
  off<T>(type: string, handler: Handler<T>): void;
}
export class LegacyInboundWorkGate {
  private retired = false;
  private failed = false;
  private readonly active = new Set<Promise<unknown>>();
  private readonly registrations: (() => void)[] = [];
  /** Register the ORIGINAL promise before a legacy catch/log path consumes it. */
  observe<T>(pending: Promise<T>): Promise<T> {
    this.active.add(pending);
    void pending.then(() => this.active.delete(pending), () => {
      this.failed = true; this.active.delete(pending);
    });
    return pending;
  }
  register<T = unknown>(socket: Socket, type: string, original: (payload: T) => unknown): void {
    if (this.retired) throw Error('legacy_inbound_retired');
    const wrapped: Handler<T> = payload => {
      // Queued phased/early replay closures retain this exact wrapper.
      if (this.retired) return;
      let pending: Promise<unknown>;
      try { pending = Promise.resolve(original(payload)); }
      catch (error) { this.failed = true; throw error; }
      this.observe(pending);
      // Return the original work lifetime to phased serialization, before logging.
      return pending.then(() => undefined);
    };
    this.registrations.push(() => socket.off(type, wrapped));
    socket.on(type, wrapped);
  }
  preflightIdle():void {
    if(this.retired||this.active.size||this.failed)throw Error('legacy_inbound_pending');
  }
  async retireAndDrain(): Promise<void> {
    this.retired = true;
    for (const remove of this.registrations.splice(0)) remove();
    while (this.active.size) await Promise.allSettled([...this.active]);
    if (this.failed) throw Error('legacy_inbound_drain_failed');
  }
}
