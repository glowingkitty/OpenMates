/** Lazy, dev-only model detector. Input/results exist only in worker/page memory. */
import { writable } from 'svelte/store';
import { detectPII, type PIIDetectionOptions, type PIIMatch } from './piiDetectionService';
import { mergeWebPIIMatches, type WebPIIEntity } from './webPIIMatches';

export const WEB_PII_ASSET_BASE = '/pii-runtime/redact-4.1.0-litert-2.6.0/';
export interface WebPIIDetectorState { status: 'disabled' | 'loading' | 'ready' | 'error'; progress?: number }
const state = writable<WebPIIDetectorState>({ status: 'disabled' });
export const webPIIDetectorState = { subscribe: state.subscribe };

export function isWebPIIModelEnabled(): boolean {
  return typeof window !== 'undefined' && import.meta.env.VITE_ENV !== 'production' &&
    ['app.dev.openmates.org', 'localhost', '127.0.0.1'].includes(window.location.hostname);
}

let worker: Worker | undefined;
let ready: Promise<void> | undefined;
let requestId = 0;
let generation = 0;
let failure: Error | undefined;
type Pending = { resolve: (value: WebPIIEntity[]) => void; reject: (reason: Error) => void; timer: ReturnType<typeof setTimeout> };
const pending = new Map<number, Pending>();

function failWorker(expectedGeneration = generation): void {
  if (expectedGeneration !== generation) return;
  const error = new Error('Enhanced private data detection is unavailable. Basic protection remains active.');
  failure = error;
  worker?.terminate(); worker = undefined; ready = undefined;
  for (const scan of queue.splice(0)) scan.reject(error);
  for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
  pending.clear();
  state.set({ status: 'error' });
}

function getWorker(): Worker {
  if (worker) return worker;
  // A classic worker is required by LiteRT's documented importScripts loader.
  worker = new Worker(`${WEB_PII_ASSET_BASE}worker.js`, { name: 'openmates-private-data' });
  const workerGeneration = generation;
  worker.onerror = () => failWorker(workerGeneration);
  worker.onmessageerror = () => failWorker(workerGeneration);
  worker.onmessage = ({ data }) => {
    if (workerGeneration !== generation) return;
    if (data.kind === 'progress') { state.set({ status: 'loading', progress: data.progress }); return; }
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
      target.postMessage({ id, kind, ...(text === undefined ? {} : { text }) });
    } catch { failWorker(requestGeneration); reject(new Error('The private data detector could not start.')); }
  });
}

export async function preloadWebPIIDetector(): Promise<void> {
  if (!isWebPIIModelEnabled()) { state.set({ status: 'disabled' }); return; }
  if (failure) throw failure;
  if (!ready) {
    const loadGeneration = generation;
    state.set({ status: 'loading' });
    ready = request('load').then(() => { if (generation === loadGeneration) state.set({ status: 'ready' }); }).catch(error => { if (generation === loadGeneration) ready = undefined; throw error; });
  }
  return ready;
}

interface Scan { text: string; options: PIIDetectionOptions; purpose: 'preview' | 'send'; resolve: (matches: PIIMatch[]) => void; reject: (error: Error) => void }
const queue: Scan[] = [];
let scanning = false;
async function drain(): Promise<void> {
  if (scanning) return;
  scanning = true;
  try {
    while (queue.length) {
      const scan = queue.shift()!;
      const scanGeneration = generation;
      try {
        await preloadWebPIIDetector();
        if (scanGeneration !== generation) throw new Error('Private data detection was reset');
        const entities = await request('scan', scan.text);
        if (scanGeneration !== generation) throw new Error('Private data detection was reset');
        scan.resolve(mergeWebPIIMatches(scan.text, entities, scan.options));
      } catch (error) {
        // Invalid model output is an enhanced-detector failure too. Keep the
        // error state until explicit retry; callers retain their basic result.
        if (scanGeneration === generation) failWorker(scanGeneration);
        scan.reject(error instanceof Error ? error : new Error('Private data detection failed'));
      }
    }
  } finally { scanning = false; }
}

export async function detectPIIForWeb(text: string, options: PIIDetectionOptions = {}, context: { purpose?: 'preview' | 'send' } = {}): Promise<PIIMatch[]> {
  if (!isWebPIIModelEnabled()) return detectPII(text, options);
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
  if (failure) return basic;
  // Only queued previews can be superseded; a send is never dropped.
  if (purpose === 'preview') {
    for (let i = queue.length - 1; i >= 0; i--) if (queue[i].purpose === 'preview') queue.splice(i, 1)[0].resolve([]);
  }
  if (queue.length >= 32) { state.set({ status: 'error' }); return basic; }
  try {
    const matches = await new Promise<PIIMatch[]>((resolve, reject) => { queue.push({ text, options: snapshot, purpose, resolve, reject }); void drain(); });
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
  worker?.terminate(); worker = undefined; ready = undefined;
  const error = new Error('Private data detection was reset');
  for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
  pending.clear();
  for (const scan of queue.splice(0)) scan.reject(error);
  state.set({ status: 'disabled' });
}
