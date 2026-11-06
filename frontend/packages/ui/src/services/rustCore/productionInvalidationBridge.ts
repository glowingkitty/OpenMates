import { registerWorkspaceCacheClear } from "../workspaceCacheLifecycle";
import { PROFILE_MUTATION_CHANNEL } from "./platformLifecycle";
import type { PriorProfileLifecycle } from "./platformLifecycle";
import { bindProductionProfileLifetime } from "./productionProfileLifecycle";

type OwnedChannel = Pick<BroadcastChannel, "addEventListener" | "removeEventListener" | "close">;
export const LEGACY_CRYPTO_CHANNEL = "openmates_crypto_v1";

/** Inactive, explicit owned-resource adapter. Install before prior-profile/key
 * capture and keep until final publication/teardown. This revokes a copied key;
 * it never captures/adopts an identity, admits, retries, writes storage or locks.
 * Messages are existing best-effort invalidations, not an atomic snapshot.
 */
export interface ProductionCoreInvalidationRelease {
  /** Revoking teardown: advances the shared lifecycle and closes the host. */
  (): void;
  /** Same-tick Worker handover to a successor admission that has already
   * installed (or installs synchronously next) its own invalidation binding.
   * Releases the listeners only: no lifecycle advance and no host close. The
   * owner must already have ended its own publications (its `closed` flag), so
   * nothing this binding guarded can still publish. A lifecycle advance here
   * would revoke the successor's freshly prepared platform snapshot (`cancelled`).
   */
  handover(): void;
}

export function bindProductionCoreInvalidations(input: {
  host: { close(): void };
  page: Pick<Window, "addEventListener" | "removeEventListener">;
  lifecycle: PriorProfileLifecycle;
  createChannel(name: string): OwnedChannel;
}): ProductionCoreInvalidationRelease {
  let closed = false;
  const releases: Array<() => void> = [];
  const releaseAll = () => {
    // One faulty platform cleanup must not retain another channel or the key.
    for (const release of releases.splice(0).reverse()) {
      try { release(); } catch { /* Resource cleanup has no authority. */ }
    }
  };
  const close = (origin?:object) => {
    if (closed) return;
    closed = true;
    // A transport reply may already have resolved while a view still awaits
    // its last profile check. Teardown must revoke that publication too.
    try { input.lifecycle.invalidateFromTeardown(origin); } catch { /* Still release the key below. */ }
    releaseAll();
    input.host.close();
  };
  const handover = () => {
    if (closed) return;
    closed = true;
    releaseAll();
  };
  const own = (release: () => void) => {
    if (closed) release(); else releases.push(release);
  };
  const revoke = close;
  try {
    const legacy = input.createChannel(LEGACY_CRYPTO_CHANNEL);
    own(() => legacy.close());
    const message = (event: Event) => {
      const value = (event as MessageEvent<unknown>).data;
      // Match the legacy receiver's clearAll boundary, including extra fields.
      // keyLoaded carries no revocation and must not trigger a new admission.
      if (typeof value === "object" && value !== null && "type" in value && value.type === "clearAll") revoke();
    };
    legacy.addEventListener("message", message);
    own(() => legacy.removeEventListener("message", message));
    legacy.addEventListener("messageerror", close);
    own(() => legacy.removeEventListener("messageerror", close));
    own(registerWorkspaceCacheClear(revoke));

    const source = input.createChannel(PROFILE_MUTATION_CHANNEL);
    let profileClosed = false;
    const profile: OwnedChannel = {
      addEventListener: source.addEventListener.bind(source),
      removeEventListener: source.removeEventListener.bind(source),
      close() { if (!profileClosed) { profileClosed = true; source.close(); } },
    };
    own(() => profile.close());
    own(bindProductionProfileLifetime({ ...input, channel: profile, host: { close:()=>close() } },origin=>close(origin)));
    return Object.assign(() => close(), { handover });
  } catch (error) { close(); throw error; }
}
