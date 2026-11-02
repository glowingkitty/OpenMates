/** Platform mutation coordination only; Rust remains the admission/policy owner.
 * Created during module evaluation, before any key-store read or auth bootstrap.
 * No key bridge, active stores, Worker creation or domain policy dependency.
 * Mutation hooks revoke optional bindings. Cross-tab notifications do not prove
 * atomic admission, and this singleton does not authorize production activation.
 */
/** Host lifecycle coordination, not auth policy. Before activation, EVERY local
 * auth/profile mutation and cross-tab invalidation must enter/invalidate here.
 * Existing legacy stores do not provide a cross-database atomic snapshot.
 */
export class PriorProfileLifecycle {
  constructor(private readonly announce: () => void = () => undefined) {}
  private generation = 1;
  private mutations = 0;
  private deliveryOrigin:object|undefined;
  private listeners = new Set<(origin?:object) => void>();
  current(): number {
    if (this.mutations !== 0) throw new Error("invalidated_snapshot");
    return this.generation;
  }
  invalidate(origin?:object): void { this.advance(true,origin); }
  /** A received revocation must not create a cross-tab rebroadcast loop. */
  invalidateFromPeer(): void { this.advance(false); }
  /** Only a known local teardown invoked synchronously by this exact observer
   * delivery may retain its cause. Generic peer/DOM calls never inherit it. */
  invalidateFromTeardown(origin?:object):void{this.advance(false,origin!==undefined&&origin===this.deliveryOrigin?origin:undefined);}
  private advance(announce: boolean,origin?:object): void {
    if (this.generation >= Number.MAX_SAFE_INTEGER) throw new Error("invalidated_snapshot");
    this.generation++;
    if (announce) { try { this.announce(); } catch { /* Revocation still reaches local observers. */ } }
    // Observers may terminate hosts/caches but cannot own mutation accounting.
    // Snapshot delivery also prevents subscriptions added during notification
    // from extending this notification indefinitely. Never log private errors.
    const previous=this.deliveryOrigin;this.deliveryOrigin=origin;
    try{for (const listener of [...this.listeners]) {
      try { if(origin===undefined)listener();else listener(origin); } catch { /* Continue notifying all healthy observers. */ }
    }}finally{this.deliveryOrigin=previous;}
  }
  /** Optional local origin is an opaque correlation token, never authority or
   * wire data. EVERY observer is still notified; existing Hosts always revoke. */
  beginMutation(origin?:object): () => void {
    this.mutations++;
    this.invalidate(origin);
    let finished = false;
    return () => { if (!finished) { finished = true; this.mutations--; this.invalidate(origin); } };
  }
  observe(listener: (origin?:object) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

export const browserProfileLifecycle = new PriorProfileLifecycle(announceProfileMutation);

/** Browser notification only: no credential/profile/key or storage access. A
 * notification revokes an existing binding; it never admits another session.
 */
export const PROFILE_MUTATION_CHANNEL = "openmates:profile-mutation:v1";
export function announceProfileMutation(): void {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return;
  let channel: BroadcastChannel | null = null;
  try {
    channel = new BroadcastChannel(PROFILE_MUTATION_CHANNEL);
    channel.postMessage({ version: 1, type: "invalidate" });
  } catch { /* Existing application mutations must preserve their result. */ }
  finally { try { channel?.close(); } catch { /* Notification cleanup cannot change application results. */ } }
}
export function isProfileMutation(value: unknown): boolean {
  return typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype
    && Reflect.ownKeys(value).length === 2 && "version" in value && value.version === 1
    && "type" in value && value.type === "invalidate";
}
