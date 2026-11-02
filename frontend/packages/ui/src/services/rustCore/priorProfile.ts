import { validProfile } from "./protocol";
import type { BrowserPersistence, CoreResponse, ProfileEvidence } from "./protocol";
import { validateMasterKey } from "./workerCredentials";
import type { BrowserCoreWorkerHost } from "./workerHost";

const EMAIL = "openmates_email_encrypted_master";
const SALT = "openmates_email_salt";
const STAY = "openmates_was_stay_logged_in";
const CLEAR = "clear_master_key_on_unload";

// Keep the existing import surface while sharing the platform singleton/class.
import { PriorProfileLifecycle } from "./platformLifecycle";
export { PriorProfileLifecycle } from "./platformLifecycle";

export interface PriorProfileSources {
  userDB: { getUserProfile(): Promise<{ user_id: string | null } | null> };
  getMasterKey(): Promise<CryptoKey | null>;
  sessionStorage: Pick<Storage, "getItem">;
  localStorage: Pick<Storage, "getItem">;
}
interface StoredEvidence {
  sessionEmail: string | null; localEmail: string | null;
  sessionSalt: string | null; localSalt: string | null;
  stay: string | null; clear: string | null;
}
function validStoredFlags(stored: StoredEvidence): boolean {
  return (stored.stay === null || stored.stay === "true") && (stored.clear === null || stored.clear === "true")
    && !(stored.stay === "true" && stored.clear === "true");
}
export interface PriorProfileSnapshot {
  readonly generation: number;
  readonly key: CryptoKey;
  readonly profile: Readonly<ProfileEvidence>;
  readonly persistence: BrowserPersistence;
}

/** Instantiate only before checkAuth/initialize can replace the prior identity.
 * Uses exact existing userDB/getMasterKey APIs, without importing active stores.
 */
export class PriorProfileReader {
  private readonly sources: PriorProfileSources;
  private readonly lifecycle: PriorProfileLifecycle;
  private readonly owned = new WeakMap<PriorProfileSnapshot, StoredEvidence>();
  constructor(sources: PriorProfileSources, lifecycle: PriorProfileLifecycle) {
    this.sources = sources; this.lifecycle = lifecycle;
  }
  private stored(): StoredEvidence {
    const { sessionStorage: session, localStorage: local } = this.sources;
    return { sessionEmail: session.getItem(EMAIL), localEmail: local.getItem(EMAIL),
      sessionSalt: session.getItem(SALT), localSalt: local.getItem(SALT),
      stay: local.getItem(STAY), clear: session.getItem(CLEAR) };
  }
  async capture(): Promise<PriorProfileSnapshot> {
    const generation = this.lifecycle.current();
    // Existing refusal rules run before a legacy getter can clean up storage.
    if (!validStoredFlags(this.stored())) throw new Error("reauthentication_required");
    const owner = (await this.sources.userDB.getUserProfile())?.user_id;
    if (this.lifecycle.current() !== generation || !validStoredFlags(this.stored())) throw new Error("invalidated_snapshot");
    const key = await this.sources.getMasterKey();
    const stored = this.stored();
    if (!owner || !key) throw new Error("reauthentication_required");
    validateMasterKey(key);
    const profile = { principal: owner, encryptedEmail: stored.sessionEmail || stored.localEmail,
      userEmailSalt: stored.sessionSalt || stored.localSalt };
    if (!validProfile(profile) || !validStoredFlags(stored)) {
      throw new Error("reauthentication_required");
    }
    const snapshot = Object.freeze({ generation, key, profile: Object.freeze(profile),
      persistence: stored.stay === "true" ? "persisted" as const : "memory_only" as const });
    this.owned.set(snapshot, stored);
    await this.assertCurrent(snapshot);
    return snapshot;
  }
  async assertCurrent(snapshot: PriorProfileSnapshot): Promise<void> {
    const previous = this.owned.get(snapshot);
    if (!previous || this.lifecycle.current() !== snapshot.generation) throw new Error("invalidated_snapshot");
    const before = this.stored();
    if (!validStoredFlags(before) || (Object.keys(previous) as (keyof StoredEvidence)[]).some(field => previous[field] !== before[field])) {
      throw new Error("invalidated_snapshot");
    }
    const owner = (await this.sources.userDB.getUserProfile())?.user_id;
    const immediatelyBeforeKey = this.stored();
    if (this.lifecycle.current() !== snapshot.generation || !validStoredFlags(immediatelyBeforeKey)
      || (Object.keys(previous) as (keyof StoredEvidence)[]).some(field => previous[field] !== immediatelyBeforeKey[field])) {
      throw new Error("invalidated_snapshot");
    }
    const key = await this.sources.getMasterKey();
    const current = this.stored();
    if (this.lifecycle.current() !== snapshot.generation || owner !== snapshot.profile.principal || key !== snapshot.key
      || (Object.keys(previous) as (keyof StoredEvidence)[]).some((field) => previous[field] !== current[field])) {
      throw new Error("invalidated_snapshot");
    }
  }
  /** Keep installed throughout the admitted Worker's lifetime, not just restore. */
  bindLifetime(host: BrowserCoreWorkerHost): () => void {
    return this.lifecycle.observe(() => host.close());
  }
  /** Guard from before capture through the whole admitted Worker lifetime.
   * The owner must call dispose on teardown; it also terminates the Worker.
   */
  async restore(host: BrowserCoreWorkerHost, signal: AbortSignal): Promise<{ response: CoreResponse; dispose: () => void }> {
    const release = this.bindLifetime(host);
    const abort = () => host.close("cancelled");
    signal.addEventListener("abort", abort, { once: true });
    const dispose = () => { signal.removeEventListener("abort", abort); release(); host.close(); };
    try {
      if (signal.aborted) throw new Error("cancelled");
      const snapshot = await this.capture();
      await this.assertCurrent(snapshot);
      if (signal.aborted) throw new Error("cancelled");
      const response = await host.request({ operation: "restore", key: snapshot.key,
        profile: snapshot.profile, persistence: snapshot.persistence }, signal);
      if (response.ok) await this.assertCurrent(snapshot);
      if (signal.aborted) throw new Error("cancelled");
      if (!response.ok) { dispose(); }
      return { response, dispose };
    } catch (error) { dispose(); throw error; }
    finally { signal.removeEventListener("abort", abort); }
  }
}
