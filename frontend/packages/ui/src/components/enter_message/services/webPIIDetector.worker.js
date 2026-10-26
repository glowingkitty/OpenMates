/* Classic Worker entry: generated SDK assets are never imported by the page/SSR. */
if (!['app.dev.openmates.org', 'localhost', '127.0.0.1'].includes(self.location.hostname)) throw new Error('Private data model is restricted to development hosts');
const ASSET_BASE = new URL('./', self.location.href).href;
const CACHE_NAME = 'openmates-pii-assets-redact-4.1.0-model-0.4.0-litert-2.6.0';
const MODEL_BASE = 'https://huggingface.co/desert-ant-labs/redact/resolve/v0.4.0/';
const MODEL_FILES = new Set(['redact.tflite', 'redact_tokenizer.bin', 'labels.json', 'redact_meta.json', 'config.json']);
const RUNTIME_FILES = new Set(['sdk.js', 'RedactWeb.wasm', 'litert_wasm_internal.js', 'litert_wasm_internal.wasm', 'litert_wasm_compat_internal.js', 'litert_wasm_compat_internal.wasm']);
const networkFetch = self.fetch.bind(self);
let modelPromise;
let chain = Promise.resolve();

function cacheable(input, init) {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, ASSET_BASE);
  const method = init?.method ?? (input instanceof Request ? input.method : 'GET');
  return method === 'GET' && !url.search &&
    ((url.href.startsWith(ASSET_BASE) && RUNTIME_FILES.has(url.href.slice(ASSET_BASE.length))) ||
     (url.href.startsWith(MODEL_BASE) && MODEL_FILES.has(url.href.slice(MODEL_BASE.length))));
}

// Strict allowlist: SDK licence/activation requests pass straight through. No
// prompt, options, result, telemetry response or unrelated fetch can be cached.
self.fetch = async (input, init) => {
  if (!cacheable(input, init)) return networkFetch(input, init);
  let cache;
  try { cache = await caches.open(CACHE_NAME); } catch { /* Private browsing may deny storage. */ }
  const cached = await cache?.match(input);
  if (cached) return cached;
  const response = await networkFetch(input, init);
  if (!response.ok) throw new Error('PII asset download failed');
  if (cache) { try { await cache.put(input, response.clone()); } catch { /* In-memory use still works. */ } }
  return response;
};

async function load() {
  if (modelPromise) return modelPromise;
  modelPromise = (async () => {
    self.postMessage({ kind: 'progress', progress: 0 });
    // Import from a cached Blob, with the bundle's import.meta.url bound to the
    // self-hosted SDK URL at build time. This permits loaded-page offline retry.
    self.__openmatesPIISdkURL = `${ASSET_BASE}sdk.js`;
    const sdkResponse = await fetch(self.__openmatesPIISdkURL);
    const sdkURL = URL.createObjectURL(new Blob([await sdkResponse.text()], { type: 'text/javascript' }));
    try {
      const { Redact } = await import(sdkURL);
      // LiteRT uses synchronous importScripts; load its cached script once via
      // Blob and provide its WASM path explicitly. No service worker required.
      const runtimeName = 'litert_wasm_compat_internal';
      const runtime = await fetch(`${ASSET_BASE}${runtimeName}.js`);
      const runtimeURL = URL.createObjectURL(new Blob([await runtime.text()], { type: 'text/javascript' }));
      self.Module = { locateFile: name => `${ASSET_BASE}${name}` };
      const litert = await import(sdkURL).then(module => module.openmatesLiteRT);
      // The fragment preserves LiteRT's full-JS-file-path detection for a Blob.
      // Let the SDK initialize LiteRT exactly once through its injected loader.
      // Calling loadLiteRt here first would make the SDK's second call throw.
      try {
        const redactor = await Redact.load({
          litert: { ...litert, loadLiteRt: () => litert.loadLiteRt(`${runtimeURL}#litert.js`) },
          litertWasmDir: ASSET_BASE, accelerator: 'wasm', onProgress: progress => {
            self.postMessage({ kind: 'progress', progress: typeof progress === 'number' ? progress : undefined });
          },
        });
        self.postMessage({ kind: 'progress', progress: 1 });
        return redactor;
      } finally { URL.revokeObjectURL(runtimeURL); }
    } finally { URL.revokeObjectURL(sdkURL); }
  })();
  return modelPromise;
}

self.onmessage = ({ data }) => {
  chain = chain.then(async () => {
    try {
      const redactor = await load();
      const items = data.kind === 'scan' ? (await redactor.redaction(data.text, { labels: [
        'GIVEN_NAME', 'SURNAME', 'STREET_NAME', 'BUILDING_NUMBER', 'SECONDARY_ADDRESS', 'CITY', 'STATE', 'ZIP_CODE', 'EMAIL', 'PHONE', 'CREDIT_CARD', 'BANK_ACCOUNT', 'ROUTING_NUMBER', 'IP_ADDRESS', 'GOVERNMENT_ID', 'PASSPORT', 'DRIVERS_LICENSE', 'TAX_ID', 'SSN', 'IMEI',
      ] })).items : [];
      self.postMessage({ id: data.id, items });
    } catch { self.postMessage({ id: data.id, error: true }); }
  });
};
