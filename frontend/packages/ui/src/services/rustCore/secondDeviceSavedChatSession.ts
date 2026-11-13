// Opt-in Rust core session that attaches to the EXISTING TypeScript login as an
// in-memory second device: the TS master key and session are handed to Rust via
// `restore_existing` (memory_only). It reads/decrypts the selected saved chat from
// the server and sends with streaming. It never writes IndexedDB and never
// replaces TS login, sync or storage; TS keeps owning the chat list.
// Loaded only by the VITE_OPENMATES_RUST_CORE build (dynamic import).
import { createOriginalSavedChatSender } from "./originalSavedChatSender";
import { bindProductionCoreInvalidations } from "./productionInvalidationBridge";
import type { ProductionCoreInvalidationRelease } from "./productionInvalidationBridge";
import { publishSelectedOnlineCachedSavedChat, publishSelectedSavedChat, publishSelectedSavedChatPage } from "./selectedSavedChat";
import type { PriorProfileLifecycle } from "./platformLifecycle";
import type { BrowserPersistence, ExistingProfileEvidence, LocalCursorSelector, LocalReadPlan, SavedPageSelector, SessionStatus } from "./protocol";
import type { LocalChatReadback, SavedChatReadback } from "./savedReadProtocol";
import type { SavedChatSelection } from "./selectedSavedChat";
import type { SendEvent } from "./sendProtocol";
import type { BrowserCoreWorkerHost } from "./workerHost";

export interface ExistingSavedChatProfile {
  readonly generation: number;
  readonly key: CryptoKey;
  readonly profile: Readonly<ExistingProfileEvidence>;
  readonly persistence: BrowserPersistence;
}
export interface ExistingSavedChatSources {
  capture(generation: number): Promise<ExistingSavedChatProfile>;
  assertCurrent(snapshot: ExistingSavedChatProfile): Promise<void>;
  executeLocalReadPlan?(snapshot: ExistingSavedChatProfile, selected: Readonly<SavedChatSelection>, plan: LocalReadPlan, signal: AbortSignal): Promise<string>;
  readEncryptedRows?(selected: Readonly<SavedChatSelection>, signal: AbortSignal): Promise<unknown>;
}
/** One Rust send operation; closures carry local correlation only. */
export interface ProductionSavedChatSend {
  readonly operationId: string;
  publishNext(publish: (event: SendEvent | null) => void): Promise<void>;
  consumeNext(consume: (event: SendEvent | null, origin: Readonly<{ chatId: string; operationId: string }>) => void): Promise<void>;
  cancel(): Promise<void>;
  close(): Promise<void>;
}
export interface ProductionSavedChatSession {
  readonly status: Readonly<SessionStatus>;
  readonly signal: AbortSignal;
  /** Full selection (owner/workspace from the admitted platform) for view guards. */
  currentSelection(): SavedChatSelection;
  /** Throws once the session or its admitted profile is no longer current. */
  assertCurrent(): void;
  publish(publish: (page: SavedChatReadback | LocalChatReadback) => void): Promise<void>;
  publishPage(selector: SavedPageSelector, publish: (page: SavedChatReadback | LocalChatReadback) => void): Promise<void>;
  /** Cache-first render from the existing retained IndexedDB rows (Rust readonly
   * plans + Worker decryption). Rejects `chat_unavailable` on a cache miss and
   * keeps the session; the caller then reconciles with `publishPage`. */
  publishCachedPage(selector: LocalCursorSelector, publish: (page: LocalChatReadback) => void): Promise<void>;
  startSend(text: string): Promise<ProductionSavedChatSend>;
  close(): void;
}

type OwnedWorker = { host: BrowserCoreWorkerHost; close(): void };
interface AdmissionInput {
  expectedPrincipal: string; signal: AbortSignal; sources: ExistingSavedChatSources;
  currentSelection(): SavedChatSelection; lifecycle: PriorProfileLifecycle;
  page: Pick<Window, "addEventListener" | "removeEventListener">;
  createChannel(name: string): Pick<BroadcastChannel, "addEventListener" | "removeEventListener" | "close">;
  createWorker(signal: AbortSignal): Promise<OwnedWorker>;
}
/** Local-only Rust admission of the existing TS key (no server call). It serves
 * cache-first reads of the retained IndexedDB rows ONLY: no server read, send,
 * mutation or socket (Rust refuses them for a local-read-only client). */
export interface LocalSavedChatSession {
  readonly status: Readonly<SessionStatus>;
  readonly signal: AbortSignal;
  /** Rejects `chat_unavailable` on a cache miss and keeps the session. */
  publishCachedPage(selector: LocalCursorSelector, publish: (page: LocalChatReadback) => void): Promise<void>;
  /** Normal server-checked admission (`restore_existing`) on this SAME Worker.
   * Ends the local session first (its Rust client is replaced and freed); any
   * failure, e.g. a revoked session, closes the Worker: nothing local survives. */
  upgrade(input: Omit<AdmissionInput, "createWorker">): Promise<ProductionSavedChatSession>;
  close(): void;
}

function localStage(name: string): void {
  if (typeof performance !== "undefined" && typeof performance.mark === "function") performance.mark(`openmates:rust:${name}`);
}

export async function admitLocalSavedChatSession(input: AdmissionInput): Promise<LocalSavedChatSession> {
  const lifetime = new AbortController();
  // The Worker outlives this local session only when upgrade() hands it over.
  const workerLifetime = new AbortController();
  let closed = false, upgrading = false, handedOver = false;
  let reading: Promise<void> | null = null;
  let witness: ExistingSavedChatProfile | null = null;
  let worker: OwnedWorker | null = null;
  let releaseInvalidations: ProductionCoreInvalidationRelease | null = null;
  const end = (handover = false) => {
    closed = true; witness = null; lifetime.abort();
    input.signal.removeEventListener("abort", close);
    const release = releaseInvalidations; releaseInvalidations = null;
    if (handover) release?.handover(); else release?.();
  };
  const close = () => {
    if (closed) return;
    try { end(); } finally { if (!handedOver) { workerLifetime.abort(); worker?.close(); } }
  };
  // Fixed-name cause marks (no content) for the open-to-rendered breakdown.
  const closeFor = (cause: string) => () => { if (!closed) localStage(`local-session-closed-${cause}`); close(); };
  input.signal.addEventListener("abort", close, { once: true });
  try {
    if (input.signal.aborted) throw new Error("cancelled");
    releaseInvalidations = bindProductionCoreInvalidations({ ...input, host: { close: closeFor("invalidated") } });
    const generation = input.lifecycle.current();
    witness = await input.sources.capture(generation);
    await input.sources.assertCurrent(witness);
    if (closed || input.lifecycle.current() !== generation) throw new Error("cancelled");
    const owned = await input.createWorker(workerLifetime.signal);
    worker = owned;
    if (closed) { owned.close(); throw new Error("cancelled"); }
    const current = () => {
      const prior = witness;
      if (!prior || closed || input.lifecycle.current() !== prior.generation
        || prior.profile.principal !== input.expectedPrincipal) throw new Error("invalidated_snapshot");
    };
    const response = await owned.host.request({ operation: "restore_local", key: witness.key,
      profile: { ...witness.profile }, persistence: "memory_only" }, lifetime.signal);
    current(); await input.sources.assertCurrent(witness!); current();
    if (!response.ok || !response.status || response.status.principal !== input.expectedPrincipal
      || response.status.persistence !== "memory_only" || response.status.localReadOnly !== true) throw new Error("unavailable");
    const status = Object.freeze({ ...response.status });
    const publishCachedPage = (selector: LocalCursorSelector, publish: (page: LocalChatReadback) => void): Promise<void> => {
      const execute = input.sources.executeLocalReadPlan;
      // Once the server check starts, later reads go to the upgraded session.
      if (!execute || reading || upgrading) return Promise.reject(new Error("unavailable"));
      const run = (async () => {
        current();
        const prior = witness!;
        await publishSelectedOnlineCachedSavedChat({ host: { request: owned.host.request.bind(owned.host), close: closeFor("read_failed") }, reader: input.sources,
          prior, status, lifecycle: input.lifecycle, signal: lifetime.signal, currentSelection: input.currentSelection, selector, mode: "local",
          executeReadPlan: (selected, plan, signal) => execute.call(input.sources, prior, selected, plan, signal),
          publish: (page: LocalChatReadback) => { current(); publish(page); } });
      })().finally(() => { if (reading === run) reading = null; });
      reading = run;
      return run;
    };
    const upgrade = async (online: Omit<AdmissionInput, "createWorker">): Promise<ProductionSavedChatSession> => {
      if (closed || upgrading) throw new Error("cancelled");
      if (online.expectedPrincipal !== input.expectedPrincipal) { close(); throw new Error("unavailable"); }
      upgrading = true;
      // The Worker serves one request at a time: let an in-flight cached read finish.
      await reading?.catch(() => undefined);
      if (closed) throw new Error("cancelled");
      // Handover, not revocation: `closed` already fences this session's views,
      // and the server-checked admission below binds its own invalidations in
      // this same synchronous tick. Advancing the lifecycle here closed the
      // caller's freshly prepared platform, so every upgrade failed `cancelled`.
      handedOver = true; end(true);
      try {
        return await admitSecondDeviceSavedChatSession({ ...online, createWorker: async () => owned });
      } catch (error) { owned.close(); throw error; }
    };
    return Object.freeze({ status, signal: lifetime.signal, publishCachedPage, upgrade, close });
  } catch (error) { close(); throw error; }
}

export async function admitSecondDeviceSavedChatSession(input: AdmissionInput): Promise<ProductionSavedChatSession> {
  const lifetime = new AbortController();
  let closed = false, busy = false;
  let witness: ExistingSavedChatProfile | null = null;
  let worker: Awaited<ReturnType<typeof input.createWorker>> | null = null;
  let releaseInvalidations: (() => void) | null = null;
  let invalidateSender: (() => void) | null = null;
  const close = () => {
    if (closed) return;
    closed = true; witness = null; invalidateSender?.(); lifetime.abort();
    input.signal.removeEventListener("abort", close);
    try { releaseInvalidations?.(); } finally { worker?.close(); }
  };
  input.signal.addEventListener("abort", close, { once: true });
  try {
    if (input.signal.aborted) throw new Error("cancelled");
    releaseInvalidations = bindProductionCoreInvalidations({ ...input, host: { close } });
    const generation = input.lifecycle.current();
    witness = await input.sources.capture(generation);
    await input.sources.assertCurrent(witness);
    if (closed || lifetime.signal.aborted || input.lifecycle.current() !== generation) throw new Error("cancelled");
    const owned = await input.createWorker(lifetime.signal);
    worker = owned;
    if (closed || lifetime.signal.aborted) { owned.close(); throw new Error("cancelled"); }
    const current = () => {
      const prior = witness;
      if (!prior || closed || lifetime.signal.aborted || input.lifecycle.current() !== prior.generation
        || prior.profile.principal !== input.expectedPrincipal) throw new Error("invalidated_snapshot");
    };
    // Hand the existing TS session/key to Rust; Rust re-checks the server session.
    const response = await owned.host.request({ operation: "restore_existing", key: witness.key,
      profile: { ...witness.profile }, persistence: "memory_only" }, lifetime.signal);
    current(); await input.sources.assertCurrent(witness!); current();
    if (!response.ok || !response.status || response.status.principal !== input.expectedPrincipal
      || response.status.persistence !== "memory_only" || response.status.localReadOnly === true) throw new Error("session_expired");
    const status = Object.freeze({ ...response.status });
    const publishPage = async (selector: SavedPageSelector, publish: (page: SavedChatReadback | LocalChatReadback) => void) => {
      if (busy) throw new Error("unavailable");
      busy = true;
      try {
        current();
        // A failed read closes the Worker host (fail closed). It must end this session
        // too, so callers re-admit a fresh Worker instead of retrying a closed host.
        const host = { request: owned.host.request.bind(owned.host), close };
        const selected = { host, reader: input.sources, prior: witness!, status, lifecycle: input.lifecycle,
          signal: lifetime.signal, currentSelection: input.currentSelection,
          publish: (page: SavedChatReadback) => { current(); publish(page); } };
        if (selector.direction === "latest") await publishSelectedSavedChat(selected);
        else await publishSelectedSavedChatPage({ ...selected, selector });
      } finally { busy = false; }
    };
    const publishCachedPage = async (selector: LocalCursorSelector, publish: (page: LocalChatReadback) => void) => {
      const execute = input.sources.executeLocalReadPlan;
      if (!execute) throw new Error("unavailable");
      if (busy) throw new Error("unavailable");
      busy = true;
      try {
        current();
        const host = { request: owned.host.request.bind(owned.host), close };
        const prior = witness!;
        await publishSelectedOnlineCachedSavedChat({ host, reader: input.sources, prior, status, lifecycle: input.lifecycle,
          signal: lifetime.signal, currentSelection: input.currentSelection, selector,
          executeReadPlan: (selected, plan, signal) => execute.call(input.sources, prior, selected, plan, signal),
          publish: (page: LocalChatReadback) => { current(); publish(page); } });
      } finally { busy = false; }
    };
    const sender = createOriginalSavedChatSender({ host: owned.host, status, signal: lifetime.signal, current, closed: () => closed,
      profile: () => witness, assertProfile: prior => input.sources.assertCurrent(prior), currentSelection: input.currentSelection,
      busy: () => busy, setBusy: value => { busy = value; }, close });
    invalidateSender = () => sender.invalidate();
    return Object.freeze({ status, signal: lifetime.signal, publishPage, publishCachedPage,
      currentSelection: () => input.currentSelection(), assertCurrent: current,
      publish: (publish: (page: SavedChatReadback | LocalChatReadback) => void) => publishPage({ direction: "latest" }, publish),
      startSend: (text: string) => sender.startSend(text), close });
  } catch (error) { close(); throw error; }
}
