/** Local model detector. Input/results exist only in worker/page memory. */
import { get, writable } from 'svelte/store';
import { personalDataStore } from '../../../stores/personalDataStore';
import { detectPII, type PIIDetectionOptions, type PIIMatch } from './piiDetectionService';
import { mergeWebPIIMatches, type WebPIIEntity } from './webPIIMatches';
import { createWebPIINetworkBroker, type WebPIIBrokerFailure } from './webPIINetworkBroker';

export const WEB_PII_ASSET_BASE = '/pii-runtime/redact-4.1.0-litert-2.6.0/';
export const WEB_PII_SCAN_BUDGET_MS = 2_500;
// The SDK uses 256-token windows. Keep enhancement limited to short inputs;
// 2,048 UTF-16 code units is roughly two windows of typical prose, not a token
// guarantee. Token-dense text is additionally bounded by the shared deadline.
export const WEB_PII_MAX_ENHANCED_CHARS = 2_048;
export interface WebPIIScanContext { purpose?: 'preview' | 'send'; deadline?: number; enhancedEnabled?: boolean }
/** Share one lazily started budget across every text field in a captured send. */
export function createWebPIIScanContext(): WebPIIScanContext { return { purpose: 'send', enhancedEnabled: isWebPIIModelEnabled() }; }
export interface WebPIIDetectorState { status: 'disabled' | 'loading' | 'ready' | 'error'; progress?: number; fallbackReason?: 'size' | 'timeout'; failureCode?: WebPIIBrokerFailure }
const state = writable<WebPIIDetectorState>({ status: 'disabled' });
export const webPIIDetectorState = { subscribe: state.subscribe };

export function isWebPIIModelSupported(): boolean {
  return typeof window !== 'undefined' &&
    ['openmates.org', 'app.openmates.org', 'app.dev.openmates.org', 'localhost', '127.0.0.1'].includes(window.location.hostname);
}

export function isWebPIIModelEnabled(): boolean {
  if (!isWebPIIModelSupported()) return false;
  installPreferenceLifecycle();
  const settings = get(personalDataStore.settings);
  return get(personalDataStore.enhancementReady) && settings.masterEnabled && settings.enhancedEnabled !== false;
}

let worker: Worker | undefined;
let broker: ReturnType<typeof createWebPIINetworkBroker> | undefined;
let brokerReady: Promise<void> | undefined;
let ready: Promise<void> | undefined;
let requestId = 0;
let generation = 0;
let failure: Error | undefined;
type Pending = { resolve: (value: WebPIIEntity[]) => void; reject: (reason: Error) => void; timer: ReturnType<typeof setTimeout> };
const pending = new Map<number, Pending>();

let preferenceLifecycleInstalled = false;
let previousPreferenceState: string | undefined;
function synchronizePreferences(): void {
  const settings = get(personalDataStore.settings);
  const current = JSON.stringify([settings.masterEnabled, settings.enhancedEnabled !== false,
    get(personalDataStore.enhancementReady)]);
  const changed = previousPreferenceState !== undefined && previousPreferenceState !== current;
  // Publish the authority first: reset notifications can synchronously read it.
  previousPreferenceState = current;
  if (changed) resetWebPIIDetector();
}
function installPreferenceLifecycle(): void {
  if (!preferenceLifecycleInstalled) {
    preferenceLifecycleInstalled = true;
    personalDataStore.settings.subscribe(synchronizePreferences);
    personalDataStore.enhancementReady.subscribe(synchronizePreferences);
  }
  // A composer subscriber may run before ours in Svelte's subscriber queue.
  // Synchronize before it starts work so our later callback cannot reset the
  // worker that it has just created for this same preference transition.
  synchronizePreferences();
}

function failWorker(expectedGeneration = generation, failureCode?: WebPIIBrokerFailure): void {
  if (expectedGeneration !== generation) return;
  const error = new Error('Enhanced private data detection is unavailable. Basic protection remains active.');
  failure = error;
  broker?.dispose(); broker = undefined; brokerReady = undefined;
  worker?.terminate(); worker = undefined; ready = undefined;
  for (const scan of queue.splice(0)) scan.reject(error);
  for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
  pending.clear();
  state.set({ status: 'error', ...(failureCode ? { failureCode } : {}) });
}

function getWorker(): Worker {
  if (worker) return worker;
  // A classic worker is required by LiteRT's documented importScripts loader.
  worker = new Worker(`${WEB_PII_ASSET_BASE}worker.js`, { name: 'openmates-private-data' });
  const workerGeneration = generation;
  const target = worker;
  broker = createWebPIINetworkBroker(worker, { onViolation: code => {
    if (worker === target) failWorker(workerGeneration, code);
  } });
  brokerReady = broker.initialize();
  // Initialization can fail before a load request attaches its continuation.
  void brokerReady.catch(() => { if (worker === target) failWorker(workerGeneration); });
  worker.onerror = event => { event?.preventDefault(); failWorker(workerGeneration); };
  worker.onmessageerror = () => failWorker(workerGeneration);
  worker.onmessage = ({ data }) => {
    if (workerGeneration !== generation || worker !== target) return;
    if (broker?.handleMessage(data)) return;
    if (data?.kind === 'progress') {
      state.set({ status: 'loading', progress: typeof data.progress === 'number' && Number.isFinite(data.progress) ? data.progress : undefined }); return;
    }
    if (!data || typeof data !== 'object') return;
    const item = pending.get(data.id);
    if (!item) return;
    clearTimeout(item.timer); pending.delete(data.id);
    if (data.error) { item.reject(new Error('Enhanced private data detection is unavailable. Basic protection remains active.')); failWorker(workerGeneration); }
    else item.resolve(data.items ?? []);
  };
  return worker;
}

function request(kind: 'load' | 'scan', text?: string): Promise<WebPIIEntity[]> {
  const requestGeneration = generation;
  return new Promise((resolve, reject) => {
    try {
      if (failure) throw failure;
      const target = getWorker();
      const id = ++requestId;
      pending.set(id, { resolve, reject, timer: setTimeout(() => failWorker(requestGeneration), kind === 'load' ? 180_000 : 60_000) });
      void brokerReady!.then(() => {
        if (requestGeneration === generation && worker === target && !failure && isWebPIIModelEnabled()) {
          target.postMessage({ id, kind, ...(text === undefined ? {} : { text }) });
        }
      }).catch(() => failWorker(requestGeneration));
    } catch { failWorker(requestGeneration); reject(new Error('The private data detector could not start.')); }
  });
}

export async function preloadWebPIIDetector(): Promise<void> {
  if (!isWebPIIModelEnabled()) { state.set({ status: 'disabled' }); return; }
  if (failure) throw failure;
  if (!ready) {
    const loadGeneration = generation;
    state.set({ status: 'loading' });
    ready = request('load').then(() => { if (generation === loadGeneration && !failure) state.set({ status: 'ready' }); }).catch(error => { if (generation === loadGeneration) ready = undefined; throw error; });
    // Hydration can cancel this shared promise before an async caller adopts
    // it (including Zone-instrumented callers). Awaiters still get its error.
    void ready.catch(() => {});
  }
  return ready;
}

interface Scan { text: string; options: PIIDetectionOptions; purpose: 'preview' | 'send'; deadline: number; phase: 'queued' | 'loading' | 'inference' | 'done'; resolve: (matches: PIIMatch[]) => void; reject: (error: Error) => void }
function isScanDone(scan: Scan): boolean { return scan.phase === 'done'; }
function expireScan(scan: Scan): boolean {
  if (Date.now() < scan.deadline) return false;
  state.set({ ...get(state), fallbackReason: 'timeout' });
  scan.reject(new Error('Enhanced private data detection exceeded its time budget'));
  return true;
}
const queue: Scan[] = [];
let scanning = false;
let activeScan: Scan | undefined;
async function drain(): Promise<void> {
  if (scanning) return;
  scanning = true;
  try {
    while (queue.length) {
      const scan = queue.shift()!;
      activeScan = scan;
      const scanGeneration = generation;
      try {
        scan.phase = 'loading';
        await preloadWebPIIDetector();
        if (isScanDone(scan)) continue;
        if (scanGeneration !== generation) throw new Error('Private data detection was reset');
        if (expireScan(scan)) continue;
        scan.phase = 'inference';
        const entities = await request('scan', scan.text);
        if (scanGeneration !== generation) throw new Error('Private data detection was reset');
        if (expireScan(scan)) continue;
        scan.resolve(mergeWebPIIMatches(scan.text, entities, scan.options));
      } catch (error) {
        // Invalid model output is an enhanced-detector failure too. Keep the
        // error state until explicit retry; callers retain their basic result.
        if (scanGeneration === generation) failWorker(scanGeneration);
        scan.reject(error instanceof Error ? error : new Error('Private data detection failed'));
      }
    }
  } finally { activeScan = undefined; scanning = false; }
}

export async function detectPIIForWeb(text: string, options: PIIDetectionOptions = {}, context: WebPIIScanContext = {}): Promise<PIIMatch[]> {
  if (!isWebPIIModelSupported()) return detectPII(text, options);
  const enhancementEnabled = isWebPIIModelEnabled();
  context.enhancedEnabled ??= enhancementEnabled;
  if (!text) return [];
  const operationGeneration = generation;
  const purpose = context.purpose ?? 'send';
  const snapshot: PIIDetectionOptions = {
    excludedIds: options.excludedIds ? new Set(options.excludedIds) : undefined,
    disabledCategories: options.disabledCategories ? new Set(options.disabledCategories) : undefined,
    personalDataEntries: options.personalDataEntries?.map(entry => ({ ...entry, additionalTexts: entry.additionalTexts ? [...entry.additionalTexts] : undefined })),
  };
  // Capture the complete existing detector result with the same options before
  // asynchronous model work. If basic detection itself fails, propagate it.
  const basic = mergeWebPIIMatches(text, [], snapshot);
  if (!context.enhancedEnabled || !enhancementEnabled) return basic;
  // Supersede obsolete previews before inference starts; sends are never dropped.
  if (purpose === 'preview') {
    if (activeScan?.purpose === 'preview' && activeScan.phase === 'loading') activeScan.resolve([]);
    for (let i = queue.length - 1; i >= 0; i--) if (queue[i].purpose === 'preview') queue.splice(i, 1)[0].resolve([]);
  }
  if (failure) return basic;
  if (text.length > WEB_PII_MAX_ENHANCED_CHARS) {
    state.set({ ...get(state), fallbackReason: 'size' });
    return basic;
  }
  context.deadline ??= Date.now() + WEB_PII_SCAN_BUDGET_MS;
  const remaining = context.deadline - Date.now();
  if (remaining <= 0) {
    state.set({ ...get(state), fallbackReason: 'timeout' });
    return basic;
  }
  if (queue.length >= 32) { state.set({ status: 'error' }); return basic; }
  try {
    const matches = await new Promise<PIIMatch[]>((resolve, reject) => {
      const scan: Scan = {
        text, options: snapshot, purpose, deadline: context.deadline!, phase: 'queued',
        resolve(matches) { clearTimeout(timer); scan.phase = 'done'; resolve(matches); },
        reject(error) { clearTimeout(timer); scan.phase = 'done'; reject(error); },
      };
      const timer = setTimeout(() => {
        if (scan.phase === 'done' || operationGeneration !== generation) return;
        // Loading may be a slow first download: let it finish in the background.
        // Only running inference must release its worker and model memory.
        if (scan.phase === 'inference') failWorker(operationGeneration);
        else {
          const index = queue.indexOf(scan);
          if (index !== -1) queue.splice(index, 1);
          state.set({ ...get(state), fallbackReason: 'timeout' });
        }
        scan.reject(new Error('Enhanced private data detection exceeded its time budget'));
      }, remaining);
      queue.push(scan);
      void drain();
    });
    if (operationGeneration !== generation) throw new Error('Private data detection was reset');
    return matches;
  } catch (error) {
    // Logout, disabling protection and reset/retry invalidate ownership. Never
    // turn cancelled work into a successful fallback from an obsolete request.
    if (operationGeneration !== generation) throw error;
    return basic;
  }
}

/** Settings disable/retry destroys all model and request memory. Asset cache stays. */
export function resetWebPIIDetector(): void {
  generation++; failure = undefined;
  broker?.dispose(); broker = undefined; brokerReady = undefined;
  worker?.terminate(); worker = undefined; ready = undefined;
  const error = new Error('Private data detection was reset');
  for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
  pending.clear();
  for (const scan of queue.splice(0)) scan.reject(error);
  state.set({ status: 'disabled' });
}
