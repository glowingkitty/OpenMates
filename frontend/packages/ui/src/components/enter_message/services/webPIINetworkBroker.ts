import { piiPinnedFiles } from './webPIIRuntimeManifest';
import { exactKeys, isInstallId, licenseStorageKey, parseLicenseJSON, PII_ASSET_PATH, PII_DEVICE_KEY, PII_HOSTS, PII_LICENSE_BASE, PII_MAX_LICENSE_BYTES, requireRecord, validateLicenseRequest, validateStoredLicense, verifyLicenseToken, type LicenseClaims } from './webPIINetworkPolicy';

const CACHE_NAME = 'openmates-pii-verified-assets-4.1.0-model-0.4.0-litert-2.6.0';
const INSTALL_STORAGE_KEY = 'openmates.pii.license.installId.v1';
const LICENSE_STORAGE_PREFIX = 'openmates.pii.license.state.v1.';
type BrokerWorker = Pick<Worker, 'postMessage'>;
export const WEB_PII_BROKER_FAILURE_CODES = ['initialization', 'message', 'asset-request', 'asset-network', 'asset-integrity', 'license-request', 'license-network', 'license-response', 'license-token', 'storage', 'worker-boundary'] as const;
export type WebPIIBrokerFailure = typeof WEB_PII_BROKER_FAILURE_CODES[number];
interface Options { onViolation: (code: WebPIIBrokerFailure) => void }
interface NetworkRequest { kind: 'pii-network'; id: number; url: string; method: string; headers: [string, string][]; body?: Uint8Array }
class BoundaryFailure extends Error {
  constructor(readonly code: WebPIIBrokerFailure) { super(code); }
}
// Only an actual rejection of the trusted host's already-validated licensing
// fetch becomes this marker. It carries no browser error text or response data.
class LicenseTransportRejection extends Error {}
async function checked<T>(code: WebPIIBrokerFailure, action: () => T | Promise<T>): Promise<T> {
  try { return await action(); }
  catch (error) { throw error instanceof BoundaryFailure ? error : new BoundaryFailure(code); }
}

function storage(): Storage | undefined { try { return globalThis.localStorage; } catch { return undefined; } }
async function readBounded(response: Response, limit: number): Promise<Uint8Array<ArrayBuffer>> {
  const length = response.headers.get('content-length');
  if (length && (!/^\d+$/.test(length) || Number(length) > limit)) throw new Error('PII response size rejected');
  const reader = response.body?.getReader();
  if (!reader) return new Uint8Array();
  // Allocate once at the reviewed limit; avoid retaining every streamed model
  // chunk alongside a second model-sized concatenation on memory-limited phones.
  const result = new Uint8Array(limit); let total = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      if (total + value.byteLength > limit) { await reader.cancel(); throw new Error('PII response size rejected'); }
      result.set(value, total); total += value.byteLength;
    }
  } finally { reader.releaseLock(); }
  return result.subarray(0, total);
}

async function verifyAsset(response: Response, expected: { sha256: string; bytes: number }): Promise<Uint8Array<ArrayBuffer>> {
  if (!response.ok || response.redirected) throw new Error('PII asset response rejected');
  const bytes = await readBounded(response, expected.bytes);
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('');
  if (bytes.length !== expected.bytes || hash !== expected.sha256) throw new Error('PII asset integrity rejected');
  return bytes;
}

/** The inference worker has connect-src 'none'. Only this host-owned broker may fetch. */
export function createWebPIINetworkBroker(worker: BrokerWorker, { onViolation }: Options) {
  const hostname = window.location.hostname;
  const origin = window.location.origin;
  const controller = new AbortController();
  const tokens = new Map<string, LicenseClaims>();
  const activatedTokens = new Set<string>();
  let disposed = false; let initialized = false; let lastRequestId = 0;
  let installId = '';
  let initialization: Promise<void> | undefined;
  // Capture trusted page fetch before the third-party SDK is loaded in its separate realm.
  const fetchFromHost = globalThis.fetch.bind(globalThis);
  const fail = (error: unknown) => { if (!disposed) { disposed = true; controller.abort(); onViolation(error instanceof BoundaryFailure ? error.code : 'message'); } };

  async function initialize() {
    if (initialization) return initialization;
    initialization = (async () => {
      if (!PII_HOSTS.has(hostname)) throw new Error('PII host rejected');
      const local = storage();
      let previous: string | null | undefined;
      try { previous = local?.getItem(INSTALL_STORAGE_KEY); } catch { /* Memory-only identity when storage is blocked. */ }
      installId = isInstallId(previous) ? previous : crypto.randomUUID();
      try { local?.setItem(INSTALL_STORAGE_KEY, installId); } catch { /* This worker retains its generated identity. */ }
      const values: Record<string, string> = { [PII_DEVICE_KEY]: installId };
      let restored: string | null | undefined;
      try { restored = local?.getItem(`${LICENSE_STORAGE_PREFIX}${hostname}`); } catch { /* Offline fresh license state. */ }
      if (restored) {
        try {
          const state = parseLicenseJSON(new TextEncoder().encode(restored));
          if (typeof state.token === 'string') tokens.set(state.token, await verifyLicenseToken(state.token, hostname));
          values[licenseStorageKey(hostname)] = validateStoredLicense(restored, tokens);
          if (state.activated === true && typeof state.token === 'string') activatedTokens.add(state.token);
        } catch {
          tokens.clear();
          try { local?.removeItem(`${LICENSE_STORAGE_PREFIX}${hostname}`); } catch { /* Invalid state is never supplied to the SDK. */ }
        }
      }
      if (disposed) return;
      initialized = true;
      worker.postMessage({ kind: 'pii-init', values });
    })();
    try { await initialization; } catch (error) { fail(new BoundaryFailure('initialization')); throw error; }
  }

  async function asset(request: NetworkRequest): Promise<{ bytes: Uint8Array; headers: [string, string][] }> {
    const prefix = `${origin}${PII_ASSET_PATH}`;
    if (request.method !== 'GET' || request.headers.length || request.body !== undefined || !request.url.startsWith(prefix)) throw new BoundaryFailure('asset-request');
    const name = request.url.slice(prefix.length);
    const expected = piiPinnedFiles[name as keyof typeof piiPinnedFiles];
    if (!Object.hasOwn(piiPinnedFiles, name) || !expected || new URL(request.url).href !== request.url) throw new BoundaryFailure('asset-request');
    const headers: [string, string][] = [['content-type', name.endsWith('.wasm') ? 'application/wasm' : name.endsWith('.js') ? 'text/javascript' : 'application/octet-stream']];
    let cache: Cache | undefined;
    try { cache = await caches.open(CACHE_NAME); } catch { /* CacheStorage is optional. */ }
    const cached = await cache?.match(request.url);
    if (cached) {
      try { return { bytes: await verifyAsset(cached, expected), headers }; }
      catch { try { await cache?.delete(request.url); } catch { /* Network below must still verify. */ } }
    }
    if (disposed) throw new Error('PII broker disposed');
    const response = await checked('asset-network', () => fetchFromHost(request.url, { method: 'GET', mode: 'same-origin', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer', cache: 'no-store', signal: controller.signal }));
    const bytes = await checked('asset-integrity', () => verifyAsset(response, expected));
    if (disposed) throw new Error('PII broker disposed');
    try { await cache?.put(request.url, new Response(bytes, { headers })); } catch { /* In-memory verified use still works. */ }
    return { bytes, headers };
  }

  async function license(request: NetworkRequest): Promise<{ bytes: Uint8Array; headers: [string, string][]; status: number }> {
    const path = request.url.slice(PII_LICENSE_BASE.length);
    if (!['license', 'activate'].includes(path) || request.method !== 'POST' || request.headers.length !== 1 ||
      request.headers[0][0] !== 'content-type' || request.headers[0][1] !== 'application/json' || !(request.body instanceof Uint8Array)) throw new BoundaryFailure('license-request');
    const body = await checked('license-request', () => validateLicenseRequest(request.body!, path, installId, hostname, new Set(tokens.keys())));
    const response = await fetchFromHost(request.url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body,
      mode: 'cors', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer', cache: 'no-store', signal: controller.signal,
    }).catch(() => { throw new LicenseTransportRejection(); });
    if (response.redirected || !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') ?? '')) throw new BoundaryFailure('license-response');
    const bytes = await checked('license-response', () => readBounded(response, PII_MAX_LICENSE_BYTES));
    const json = await checked('license-response', () => parseLicenseJSON(bytes));
    if (response.ok) {
      await checked('license-response', () => exactKeys(json, [path === 'license' ? 'token' : 'activated'],
        path === 'license' ? ['serverTime', 'licenseId', 'period', 'periodEnd'] : ['serverTime', 'period']));
      if (json.serverTime !== undefined && (typeof json.serverTime !== 'string' || !/^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(json.serverTime) || !Number.isFinite(Date.parse(json.serverTime)))) throw new BoundaryFailure('license-response');
      if (path === 'license') {
        if (typeof json.token !== 'string') throw new BoundaryFailure('license-response');
        const token = json.token;
        const claims = await checked('license-token', () => verifyLicenseToken(token, hostname));
        // The pinned SDK's LicensingTests.swift grantReply includes this
        // metadata even though its decoder consumes only token/serverTime.
        // Accept the complete known triple only when the verified JWT agrees;
        // authorize no activation token from contradictory or partial metadata.
        if (['licenseId', 'period', 'periodEnd'].some(key => Object.hasOwn(json, key)) &&
          (json.licenseId !== claims.lid || json.period !== claims.period || json.periodEnd !== claims.periodEnd)) {
          throw new BoundaryFailure('license-response');
        }
        tokens.set(json.token, claims);
      } else {
        if (typeof json.activated !== 'boolean') throw new BoundaryFailure('license-response');
        const token = (JSON.parse(body) as { license: string }).license;
        const claims = tokens.get(token);
        // The same pinned fixture's activatedReply includes the reported
        // period. It must match the verified token actually sent to activate,
        // including a late activation for an earlier calendar month.
        if (!claims || (Object.hasOwn(json, 'period') && json.period !== claims.period)) throw new BoundaryFailure('license-response');
        if (json.activated) activatedTokens.add(token);
      }
    } else {
      await checked('license-response', () => exactKeys(json, ['error']));
      if (typeof json.error !== 'string' || !json.error.length || json.error.length > 256) throw new BoundaryFailure('license-response');
    }
    const headers: [string, string][] = [['content-type', 'application/json']];
    const retryAfter = response.headers.get('retry-after');
    if (retryAfter !== null) {
      if (!/^\d{1,5}$/.test(retryAfter)) throw new BoundaryFailure('license-response');
      headers.push(['retry-after', retryAfter]);
    }
    return { bytes, status: response.status, headers };
  }

  async function network(data: unknown) {
    const record = requireRecord(data);
    exactKeys(record, ['kind', 'id', 'url', 'method', 'headers'], ['body']);
    if (!initialized || !Number.isSafeInteger(record.id) || (record.id as number) <= lastRequestId || typeof record.url !== 'string' || typeof record.method !== 'string' ||
      !Array.isArray(record.headers) || record.headers.some(header => !Array.isArray(header) || header.length !== 2 || header.some(value => typeof value !== 'string'))) throw new Error('PII network message rejected');
    lastRequestId = record.id as number;
    const request = record as unknown as NetworkRequest;
    let result: Awaited<ReturnType<typeof license>> | Awaited<ReturnType<typeof asset>>;
    try { result = request.url.startsWith(PII_LICENSE_BASE) ? await license(request) : await asset(request); }
    catch (error) {
      if (!(error instanceof LicenseTransportRejection)) throw error;
      // Preserve the SDK's documented five-minute network retry without
      // fabricating an HTTP response, license, activation or successful report.
      if (!disposed) worker.postMessage({ kind: 'pii-network-error', id: request.id });
      return;
    }
    if (disposed) return;
    worker.postMessage({ kind: 'pii-network-result', id: request.id, status: 'status' in result ? result.status : 200, headers: result.headers, body: result.bytes }, [result.bytes.buffer]);
  }

  function persist(data: unknown) {
    const record = requireRecord(data); exactKeys(record, ['kind', 'key', 'value']);
    if (!initialized || typeof record.value !== 'string') throw new Error('PII storage message rejected');
    if (record.key === PII_DEVICE_KEY && record.value === installId) return;
    if (record.key !== licenseStorageKey(hostname)) throw new Error('PII storage key rejected');
    const value = validateStoredLicense(record.value, tokens);
    const state = JSON.parse(value) as { activated: boolean; token?: string };
    if (state.activated && (!state.token || !activatedTokens.has(state.token))) throw new Error('PII unacknowledged activation state rejected');
    try { storage()?.setItem(`${LICENSE_STORAGE_PREFIX}${hostname}`, value); } catch { /* Keep authenticated state in worker memory. */ }
  }

  return {
    initialize,
    handleMessage(data: unknown): boolean {
      if (!data || typeof data !== 'object' || !('kind' in data) || !['pii-network', 'pii-storage', 'pii-boundary-violation', 'pii-network-error', 'pii-network-result', 'pii-init'].includes(String(data.kind))) return false;
      if (!disposed) {
        if (data.kind === 'pii-network') void network(data).catch(fail);
        else if (data.kind === 'pii-storage') { try { persist(data); } catch { fail(new BoundaryFailure('storage')); } }
        else fail(new BoundaryFailure(data.kind === 'pii-boundary-violation' ? 'worker-boundary' : 'message'));
      }
      return true;
    },
    dispose() { disposed = true; controller.abort(); tokens.clear(); activatedTokens.clear(); },
  };
}
