/* Classic Worker entry: generated SDK assets are never imported by the page/SSR. */
if (!['openmates.org', 'app.openmates.org', 'app.dev.openmates.org', 'localhost', '127.0.0.1'].includes(self.location.hostname)) throw new Error('Private data model host rejected');
const ASSET_BASE = new URL('./', self.location.href).href;
let modelPromise;
let chain = Promise.resolve();
let initialized = false;
let modelReady = false;
let loadStage = 'worker-message';
let requestId = 0;
const pendingFetches = new Map();
const diagnosticCodes = new Set(['fetch-input', 'fetch-options', 'fetch-credentials', 'fetch-body', 'storage-input', 'transport',
  'csp-connect', 'csp-script', 'csp-worker', 'csp-other', 'worker-sdk-asset', 'worker-sdk-import', 'worker-runtime-asset',
  'worker-runtime-load', 'worker-model-load', 'worker-scan', 'worker-message', 'license-network-rejected', 'function-construction', 'normalization-input']);
const diagnostic = code => self.postMessage({ kind: 'pii-diagnostic', code: diagnosticCodes.has(code) ? code : 'worker-message' });
const rejectTransport = code => { diagnostic(code); self.postMessage({ kind: 'pii-boundary-violation' }); throw new Error('PII worker transport rejected'); };
self.addEventListener('securitypolicyviolation', event => {
  const directive = event.effectiveDirective;
  diagnostic(directive === 'connect-src' ? 'csp-connect' : ['script-src', 'script-src-elem'].includes(directive) ? 'csp-script'
    : ['worker-src', 'child-src'].includes(directive) ? 'csp-worker' : 'csp-other');
  self.postMessage({ kind: 'pii-boundary-violation' });
});

// Pinned SDK 4.1.0 Sources/TextNormalization/JSNormalization.swift lazily asks
// JavaScriptKit to construct exactly these two functions on the first scan.
// Supply reviewed, already-parsed closures instead of evaluating either body.
// All other Function requests still fail closed, and script-src continues to
// forbid eval (including constructors recovered through native prototypes).
const normalizeString = String.prototype.normalize;
function normalizeNFKC(s) {
  if (typeof s !== 'string') return rejectTransport('normalization-input');
  return Reflect.apply(normalizeString, s, ['NFKC']);
}
function normalizeNFC(s) {
  if (typeof s !== 'string') return rejectTransport('normalization-input');
  return Reflect.apply(normalizeString, s, ['NFC']);
}
function approvedNormalizationFunction(...args) {
  if (args.length === 2 && args[0] === 's') {
    if (args[1] === "return s.normalize('NFKC')") return normalizeNFKC;
    if (args[1] === "return s.normalize('NFC')") return normalizeNFC;
  }
  return rejectTransport('function-construction');
}
// Preserve Function instanceof checks in LiteRT and JavaScriptKit as well as
// their new/Reflect.construct calls; never invoke or save a native-constructor
// fallback. The normal function prototype's constructor stays blocked by CSP.
Object.defineProperty(approvedNormalizationFunction, 'prototype', { value: Object.getPrototypeOf(normalizeNFKC), writable: false });
Object.defineProperty(self, 'Function', { configurable: false, writable: false, value: Object.freeze(approvedNormalizationFunction) });

// There is deliberately no retained native fetch. The worker response's CSP
// independently denies every direct connection and network script/subworker.
Object.defineProperty(self, 'fetch', { configurable: false, writable: false, value: async (input, init = {}) => {
  if (!(typeof input === 'string' || input instanceof URL)) return rejectTransport('fetch-input');
  const url = new URL(input, ASSET_BASE).href;
  const isAsset = url.startsWith(ASSET_BASE);
  if (Object.keys(init).some(key => !['method', 'headers', 'body', 'signal', ...(isAsset ? ['credentials'] : [])].includes(key))) return rejectTransport('fetch-options');
  // Emscripten requests same-origin credentials for WASM. The host always uses
  // credentials:omit; no cookie/authorization/referrer reaches either endpoint.
  if (init.credentials !== undefined && init.credentials !== 'same-origin' && init.credentials !== 'omit') return rejectTransport('fetch-credentials');
  if (init.body !== undefined && !(init.body instanceof Uint8Array)) return rejectTransport('fetch-body');
  if (init.signal?.aborted) throw new Error('PII fetch aborted');
  const id = ++requestId;
  const headers = Array.from(new Headers(init.headers).entries());
  const body = init.body?.slice();
  return new Promise((resolve, reject) => {
    const abort = () => { pendingFetches.delete(id); reject(new Error('PII fetch aborted')); };
    init.signal?.addEventListener('abort', abort, { once: true });
    pendingFetches.set(id, {
      resolve: result => { init.signal?.removeEventListener('abort', abort); resolve(result); },
      reject: error => { init.signal?.removeEventListener('abort', abort); reject(error); },
    });
    self.postMessage({ kind: 'pii-network', id, url, method: init.method ?? 'GET', headers, ...(body ? { body } : {}) }, body ? [body.buffer] : []);
  });
} });
for (const transport of ['XMLHttpRequest', 'WebSocket', 'EventSource', 'Worker', 'SharedWorker']) {
  Object.defineProperty(self, transport, { configurable: false, writable: false, value: function () { return rejectTransport('transport'); } });
}

async function load() {
  if (modelPromise) return modelPromise;
  modelPromise = (async () => {
    self.postMessage({ kind: 'progress', progress: 0 });
    // Import from a cached Blob, with the bundle's import.meta.url bound to the
    // self-hosted SDK URL at build time. This permits loaded-page offline retry.
    self.__openmatesPIISdkURL = `${ASSET_BASE}sdk.js`;
    loadStage = 'worker-sdk-asset';
    const sdkResponse = await fetch(self.__openmatesPIISdkURL);
    const sdkURL = URL.createObjectURL(new Blob([await sdkResponse.text()], { type: 'text/javascript' }));
    try {
      loadStage = 'worker-sdk-import';
      const { Redact } = await import(sdkURL);
      // LiteRT uses synchronous importScripts; load its cached script once via
      // Blob and provide its WASM path explicitly. No service worker required.
      const runtimeName = 'litert_wasm_compat_internal';
      loadStage = 'worker-runtime-asset';
      const runtime = await fetch(`${ASSET_BASE}${runtimeName}.js`);
      const runtimeURL = URL.createObjectURL(new Blob([await runtime.text()], { type: 'text/javascript' }));
      self.Module = { locateFile: name => `${ASSET_BASE}${name}` };
      const litert = await import(sdkURL).then(module => module.openmatesLiteRT);
      // The fragment preserves LiteRT's full-JS-file-path detection for a Blob.
      // Let the SDK initialize LiteRT exactly once through its injected loader.
      // Calling loadLiteRt here first would make the SDK's second call throw.
      try {
        loadStage = 'worker-model-load';
        const redactor = await Redact.load({
          litert: { ...litert, loadLiteRt: async () => {
            loadStage = 'worker-runtime-load';
            const loaded = await litert.loadLiteRt(`${runtimeURL}#litert.js`);
            loadStage = 'worker-model-load';
            return loaded;
          } },
          modelBaseUrl: `${ASSET_BASE}model/`,
          litertWasmDir: ASSET_BASE, accelerator: 'wasm', onProgress: progress => {
            self.postMessage({ kind: 'progress', progress: typeof progress === 'number' ? progress : undefined });
          },
        });
        self.postMessage({ kind: 'progress', progress: 1 });
        modelReady = true;
        return redactor;
      } finally { URL.revokeObjectURL(runtimeURL); }
    } finally { URL.revokeObjectURL(sdkURL); }
  })();
  return modelPromise;
}

self.onmessage = ({ data }) => {
  if (data.kind === 'pii-network-error') {
    const pending = pendingFetches.get(data.id);
    if (pending) {
      pendingFetches.delete(data.id);
      diagnostic('license-network-rejected');
      pending.reject(new TypeError('Network request failed'));
    }
    return;
  }
  if (data.kind === 'pii-network-result') {
    const pending = pendingFetches.get(data.id);
    if (pending) {
      pendingFetches.delete(data.id);
      try { pending.resolve(new Response(data.body, { status: data.status, headers: data.headers })); }
      catch { pending.reject(new Error('PII broker response rejected')); }
    }
    return;
  }
  if (data.kind === 'pii-init') {
    if (initialized) return;
    initialized = true;
    const values = new Map(Object.entries(data.values));
    // SDK-supported synchronous Web-Storage seam. Only the host can approve
    // persistent writes; the SDK never sees page storage or account content.
    Object.defineProperty(self, '__dalUsageStore', { configurable: false, writable: false, value: Object.freeze({
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => {
        if (typeof key !== 'string' || typeof value !== 'string') return rejectTransport('storage-input');
        values.set(key, value);
        self.postMessage({ kind: 'pii-storage', key, value });
      },
    }) });
    return;
  }
  chain = chain.then(async () => {
    try {
      if (!initialized || !['load', 'scan'].includes(data.kind)) { loadStage = 'worker-message'; throw new Error('PII worker is not initialized'); }
      const redactor = await load();
      const items = data.kind === 'scan' ? (await redactor.redaction(data.text, { labels: [
        'GIVEN_NAME', 'SURNAME', 'STREET_NAME', 'BUILDING_NUMBER', 'SECONDARY_ADDRESS', 'CITY', 'STATE', 'ZIP_CODE', 'EMAIL', 'PHONE', 'CREDIT_CARD', 'BANK_ACCOUNT', 'ROUTING_NUMBER', 'IP_ADDRESS', 'GOVERNMENT_ID', 'PASSPORT', 'DRIVERS_LICENSE', 'TAX_ID', 'SSN', 'IMEI',
      ] })).items : [];
      self.postMessage({ id: data.id, items });
    } catch { diagnostic(modelReady ? 'worker-scan' : loadStage); self.postMessage({ id: data.id, error: true }); }
  });
};
