import { executeBrowserLocalReadPlan } from "./browserLocalCursorIO";
import { parseBrowserLocalReadPlan } from "./protocol";
/** Deployed browser-source adapter for the explicit production saved-read owner.
 * The public entry derives its owner/auth/Team state from actual application
 * stores, settles the existing getMasterKey cleanup and reads existing user_db.
 * No caller JSON owner, encrypted-email prerequisite, key export or enrollment.
 * This is TS-equivalent local evidence; Rust's fresh session/expected-principal
 * checks still own remote authority. No cross-store atomicity/association ACK.
 */
import { awaitBrowserRead, holdExistingDatabase, holdExistingProfileDatabase, readExistingSavedChatRows, readHeldProfileOwner } from "./existingSavedChatIO";
import type { PriorProfileLifecycle } from "./platformLifecycle";
import type { ExistingSavedChatProfile, ExistingSavedChatSources } from "./secondDeviceSavedChatSession";
import type { SavedChatSelection } from "./selectedSavedChat";

interface BrowserContext {
  ownerId: string | null; authenticated: boolean; initialized: boolean; checking: boolean;
  deviceVerification: boolean; loggingOut: boolean; forcedLogout: boolean;
  loginGeneration: number; teamId: string | null; teamEpoch: number; workspaceEpoch: number;
}
interface BrowserPort {
  signal: AbortSignal; lifecycle: PriorProfileLifecycle; database: IDBFactory;
  sessionStorage: Pick<Storage, "getItem">; localStorage: Pick<Storage, "getItem">;
  context(): BrowserContext;
  settleBootstrap(signal: AbortSignal): Promise<void>;
  getMasterKey(): Promise<CryptoKey | null>;
  /** `local_first`: TS-optimistic local state (before its server check finishes)
   * admits ONLY the Worker's local-only read session; the in-flight auth check
   * (`checking`) neither blocks nor invalidates it. Every other field still does. */
  mode?: "server_checked" | "local_first";
}
export interface PreparedSavedChatPlatform {
  readonly expectedPrincipal: string;
  readonly sessionId: string;
  readonly sources: ExistingSavedChatSources;
  selection(selected: Omit<SavedChatSelection, "ownerId" | "teamId" | "workspaceEpoch">): SavedChatSelection;
  /** Restrictive native IO selectors from this actual captured platform. */
  cacheScope():Readonly<{lifecycleGeneration:number;workspaceEpoch:number}>;
  close(): void;
}
const contextFields = ["ownerId", "authenticated", "initialized", "checking", "deviceVerification", "loggingOut", "forcedLogout", "loginGeneration", "teamId", "teamEpoch", "workspaceEpoch"] as const;
function allowed(context: BrowserContext, local: boolean): boolean {
  return typeof context.ownerId === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(context.ownerId)
    && context.authenticated && context.initialized && (local || !context.checking) && !context.deviceVerification
    && !context.loggingOut && !context.forcedLogout && context.teamId === null;
}
function opaqueMaster(key: CryptoKey | null): key is CryptoKey {
  return !!key && typeof CryptoKey !== "undefined" && key instanceof CryptoKey && key.type === "secret"
    && key.algorithm.name === "AES-GCM" && (key.algorithm as AesKeyAlgorithm).length === 256
    && key.usages.includes("encrypt") && key.usages.includes("decrypt");
}
/** Explicit port exists for pure platform checks. Only createBrowserSavedChatPlatform
 * below binds it to actual application stores; port objects confer no authority.
 */
export async function prepareSavedChatPlatform(port: BrowserPort): Promise<PreparedSavedChatPlatform> {
  const lifetime = new AbortController();
  let closed = false, key: CryptoKey | null = null;
  let release = () => {};
  const owned = new WeakSet<ExistingSavedChatProfile>();
  const local = port.mode === "local_first";
  const compared = contextFields.filter(field => !local || field !== "checking");
  // One user_db / chats_db connection each for this platform's repeated checks
  // and plan reads (no per-read databases() + open). A versionchange or forced
  // close invalidates the platform's reads for good (fail closed).
  const profileDatabase = holdExistingProfileDatabase(port.database);
  const chatsDatabase = holdExistingDatabase(port.database, "chats_db");
  const close = () => { key = null; if (closed) return; closed = true; lifetime.abort(); profileDatabase.close(); chatsDatabase.close(); release(); port.signal.removeEventListener("abort", close); };
  port.signal.addEventListener("abort", close, { once: true });
  const active = () => { if (closed || port.signal.aborted) throw new Error("cancelled"); };
  const flags = () => JSON.stringify([
    port.localStorage.getItem("openmates_was_stay_logged_in"), port.sessionStorage.getItem("clear_master_key_on_unload"),
    port.sessionStorage.getItem("openmates_email_encrypted_master"), port.localStorage.getItem("openmates_email_encrypted_master"),
    port.sessionStorage.getItem("openmates_email_salt"), port.localStorage.getItem("openmates_email_salt"),
    port.localStorage.getItem("openmates_needs_cleanup"), port.localStorage.getItem("openmates_user_db_initialized"),
    port.sessionStorage.getItem("session_id"),
  ]);
  try {
    active(); if (!local) await port.settleBootstrap(lifetime.signal); active();
    const before = port.context(); if (!allowed(before, local)) throw new Error("unavailable");
    // Preserve the deployed getter's memory/IDB and asynchronous clear-on-load
    // behavior before an owned Worker/lifecycle binding exists. Do not replace
    // its implementation with raw IDB reads or reinterpret stayLoggedIn flags.
    key = await awaitBrowserRead(port.getMasterKey(), lifetime.signal); active();
    const baseline = port.context();
    if (!allowed(baseline, local) || compared.some(field => field !== "workspaceEpoch" && before[field] !== baseline[field]) || !opaqueMaster(key)) throw new Error("unavailable");
    const generation = port.lifecycle.current(), stored = flags();
    const sessionId = port.sessionStorage.getItem("session_id");
    if (!sessionId || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(sessionId)) throw new Error("unavailable");
    const persistence = port.localStorage.getItem("openmates_was_stay_logged_in") === "true" ? "persisted" as const : "memory_only" as const;
    const current = () => {
      active(); const now = port.context();
      if (!key || port.lifecycle.current() !== generation || !allowed(now, local)
        || compared.some(field => baseline[field] !== now[field]) || flags() !== stored) throw new Error("invalidated_snapshot");
    };
    release = port.lifecycle.observe(close);
    const sameProfile = async (signal:AbortSignal=lifetime.signal) => {
      const activeRead=()=>{current();if(signal.aborted)throw Error("cancelled");};
      activeRead();
      const owner = await readHeldProfileOwner(profileDatabase, signal, activeRead); activeRead();
      const actual = await awaitBrowserRead(port.getMasterKey(), signal); activeRead();
      if (owner !== baseline.ownerId || actual !== key) throw new Error("invalidated_snapshot");
    };
    await sameProfile(); current();
    const sources: ExistingSavedChatSources = {
      async capture(requestedGeneration) {
        current(); if (requestedGeneration !== generation) throw new Error("invalidated_snapshot");
        await sameProfile(); current();
        const snapshot = Object.freeze({ generation, key: key!, profile: Object.freeze({ principal: baseline.ownerId!, hashedEmail: null, userEmailSalt: null }), persistence });
        owned.add(snapshot); return snapshot;
      },
      async assertCurrent(snapshot) {
        current(); if (!owned.has(snapshot) || snapshot.generation !== generation || snapshot.key !== key) throw new Error("invalidated_snapshot");
        await sameProfile(); current();
      },
      async executeLocalReadPlan(snapshot,selected,plan,signal){
        current();
        if(!owned.has(snapshot)||snapshot.generation!==generation||snapshot.key!==key||selected.ownerId!==baseline.ownerId
          ||selected.teamId!==null||selected.workspaceEpoch!==baseline.workspaceEpoch)throw Error("invalidated_snapshot");
        const combined=new AbortController(),abort=()=>combined.abort();const signals=[signal,lifetime.signal];
        for(const source of signals){source.addEventListener("abort",abort,{once:true});if(source.aborted)abort();}
        const activeRead=()=>{current();if(combined.signal.aborted)throw Error("cancelled");};
        try{
          // The post-read check below withholds every packet read under a replaced
          // profile, so local-first mode skips the redundant pre-read IDB owner read
          // (synchronous lifecycle/context/flag guards still run before the read).
          activeRead();if(!local)await sameProfile(combined.signal);activeRead();
          const encoded=JSON.stringify(plan),parsed=parseBrowserLocalReadPlan(encoded);
          if(parsed.owner!==baseline.ownerId||parsed.chatId!==selected.chatId)throw Error("invalidated_snapshot");
          const packet=await executeBrowserLocalReadPlan(port.database,encoded,combined.signal,activeRead,IDBKeyRange,undefined,chatsDatabase);activeRead();
          await sameProfile(combined.signal);activeRead();return packet;
        }finally{for(const source of signals)source.removeEventListener("abort",abort);}
      },
      async readEncryptedRows(selected, signal) {
        current();
        if (selected.ownerId !== baseline.ownerId || selected.teamId !== null || selected.workspaceEpoch !== baseline.workspaceEpoch) throw new Error("invalidated_snapshot");
        await sameProfile(); current();
        const combined = new AbortController(), abort = () => combined.abort();
        const signals = [signal, lifetime.signal];
        for (const source of signals) { source.addEventListener("abort", abort, { once: true }); if (source.aborted) abort(); }
        try {
          const result = await readExistingSavedChatRows(port.database, selected, combined.signal, current); current();
          await sameProfile(); current(); return result;
        } finally { for (const source of signals) source.removeEventListener("abort", abort); }
      },
    };
    return { expectedPrincipal: baseline.ownerId!, sessionId, sources,
      selection(selected) { current(); return { ...selected, ownerId: baseline.ownerId!, teamId: baseline.teamId, workspaceEpoch: baseline.workspaceEpoch }; },
      cacheScope(){current();return Object.freeze({lifecycleGeneration:generation,workspaceEpoch:baseline.workspaceEpoch});},close };
  } catch (error) { close(); throw error; }
}
/** No explicit owner/auth booleans are accepted here. Dynamic imports keep this
 * inactive adapter out of ordinary bootstrap and avoid an auth startup cycle.
 */
export async function createBrowserSavedChatPlatform(signal: AbortSignal, mode: "server_checked" | "local_first" = "server_checked"): Promise<PreparedSavedChatPlatform> {
  if (typeof window === "undefined" || signal.aborted) throw new Error("unavailable");
  const [{ get }, auth, profile, team, signup, bootstrap, keys, workspace, lifecycle] = await Promise.all([
    import("svelte/store"), import("../../stores/authStore"), import("../../stores/userProfile"), import("../../stores/teamStore"),
    import("../../stores/signupState"), import("../../stores/authBootstrapReadiness"), import("../cryptoKeyStorage"),
    import("../workspaceCacheLifecycle"), import("./platformLifecycle"),
  ]);
  return prepareSavedChatPlatform({ signal, mode, lifecycle: lifecycle.browserProfileLifecycle, database: indexedDB,
    sessionStorage, localStorage, settleBootstrap: bootstrap.waitForAuthBootstrapReadiness, getMasterKey: keys.getMasterKey,
    context: () => {
      const state = get(auth.authStore), currentProfile = get(profile.userProfile), context = get(team.activeTeamContext);
      return { ownerId: currentProfile.user_id, authenticated: state.isAuthenticated, initialized: state.isInitialized,
        checking: get(auth.isCheckingAuth), deviceVerification: get(auth.needsDeviceVerification), loggingOut: get(signup.isLoggingOut),
        forcedLogout: get(signup.forcedLogoutInProgress), loginGeneration: auth.getLoginSessionGeneration(),
        teamId: context.teamId, teamEpoch: context.epoch, workspaceEpoch: workspace.getWorkspaceCacheEpoch() };
    } });
}
