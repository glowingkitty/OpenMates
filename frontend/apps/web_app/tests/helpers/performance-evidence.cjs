'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const MAX_DURATIONS = 512;
const number = (v) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= Number.MAX_SAFE_INTEGER ? v : null;
const hash = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');

// Install before navigation: the browser's default ResourceTiming buffer can
// discard entries before getEntriesByType sees them. Keep a bounded buffer and
// report saturation; a buffer-full event is not an exact dropped-entry count.
function installResourceTimingCapture() {
  if (globalThis.__openmatesResourceTimingCaptureV1) return;
  const state = { installed: false, requestedCapacity: 4096, bufferFullEvents: 0 };
  Object.defineProperty(globalThis, '__openmatesResourceTimingCaptureV1', { value: state });
  try {
    performance.setResourceTimingBufferSize(state.requestedCapacity);
    performance.addEventListener('resourcetimingbufferfull', () => {
      state.bufferFullEvents = Math.min(Number.MAX_SAFE_INTEGER, state.bufferFullEvents + 1);
    });
    state.installed = true;
  } catch { /* missing APIs leave capture explicitly unverified */ }
}

// Self-contained browser function: raw resource names are classified in-page
// and NEVER returned to the runner or an attachment. No additional requests.
function browserResourceSnapshot() {
  const entries = performance.getEntriesByType('resource');
  const limits = { resourceEntries: 4096 };
  const buckets = Object.fromEntries(['javascript', 'observedWasmResource', 'other'].map((kind) => [kind, {
    count: 0, transferBytes: 0, encodedBodyBytes: 0, decodedBodyBytes: 0,
    firstParty: 0, thirdParty: 0, opaqueOrigin: 0,
    zeroTransferWithBody: 0, allSizesZero: 0, deliveryCacheReported: 0, serviceWorkerIntercepted: 0,
  }]));
  let devModuleObserved = false;
  const size = (v) => typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.min(v, Number.MAX_SAFE_INTEGER) : 0;
  for (const entry of entries.slice(0, limits.resourceEntries)) {
    let kind = 'other', origin = 'opaqueOrigin';
    try {
      const url = new URL(entry.name, location.href);
      if (['http:', 'https:'].includes(url.protocol)) origin = url.origin === location.origin ? 'firstParty' : 'thirdParty';
      if (/\.wasm$/i.test(url.pathname)) kind = 'observedWasmResource';
      else if (/\.m?js$/i.test(url.pathname) || entry.initiatorType === 'script') kind = 'javascript';
      if (origin === 'firstParty' && /\/@vite\/client|\/@id\/|\/node_modules\/\.vite\//.test(url.pathname)) devModuleObserved = true;
    } catch { /* opaque/unparseable names remain counters only */ }
    const b = buckets[kind];
    b.count += 1; b[origin] += 1;
    const transfer = size(entry.transferSize), encoded = size(entry.encodedBodySize), decoded = size(entry.decodedBodySize);
    b.transferBytes += transfer; b.encodedBodyBytes += encoded; b.decodedBodyBytes += decoded;
    if (transfer === 0 && (encoded > 0 || decoded > 0)) b.zeroTransferWithBody += 1;
    if (transfer === 0 && encoded === 0 && decoded === 0) b.allSizesZero += 1;
    if (entry.deliveryType === 'cache') b.deliveryCacheReported += 1;
    if (entry.workerStart > 0) b.serviceWorkerIntercepted += 1;
  }
  const navigation = performance.getEntriesByType('navigation')[0];
  const memory = performance.memory;
  const capture = globalThis.__openmatesResourceTimingCaptureV1;
  return {
    buckets, devModuleObserved, observedDevice: { pixelRatio: globalThis.devicePixelRatio ?? null, hardwareConcurrency: navigator.hardwareConcurrency ?? null, deviceMemoryGiB: navigator.deviceMemory ?? null }, totalEntries: entries.length, omittedEntries: Math.max(0, entries.length - limits.resourceEntries),
    capture: { installed: capture?.installed === true, requestedCapacity: capture ? size(capture.requestedCapacity) : null, bufferFullEvents: capture ? size(capture.bufferFullEvents) : null },
    navigation: navigation ? { transferBytes: size(navigation.transferSize), encodedBodyBytes: size(navigation.encodedBodySize), decodedBodyBytes: size(navigation.decodedBodySize), zeroTransferWithBody: navigation.transferSize === 0 && (navigation.encodedBodySize > 0 || navigation.decodedBodySize > 0), allSizesZero: navigation.transferSize === 0 && navigation.encodedBodySize === 0 && navigation.decodedBodySize === 0, deliveryCacheReported: navigation.deliveryType === 'cache', serviceWorkerIntercepted: navigation.workerStart > 0 } : null,
    usedJSHeapBytes: memory && Number.isFinite(memory.usedJSHeapSize) ? memory.usedJSHeapSize : null,
    serviceWorkerControlled: Boolean(navigator.serviceWorker?.controller),
  };
}
function stats(values) {
  const valid = (Array.isArray(values) ? values : []).filter((v) => number(v) !== null).sort((a,b) => a-b);
  const n = valid.length, middle = Math.floor(n/2);
  return { count: n, median: n ? (n%2 ? valid[middle] : (valid[middle-1]+valid[middle])/2) : null,
    p95: n ? valid[Math.ceil(n*0.95)-1] : null, longest: n ? valid[n-1] : null,
    invalidCount: (Array.isArray(values) ? values.length : 0)-n };
}
function sanitizeSample(sample, runIndex) {
  const durations = (values) => ({ values: (Array.isArray(values) ? values : []).filter((v) => number(v) !== null).slice(0, MAX_DURATIONS),
    omittedValues: Math.max(0, (Array.isArray(values) ? values : []).filter((v) => number(v) !== null).length-MAX_DURATIONS), ...stats(values) });
  const metrics = Object.fromEntries(['chunks','flushes','fullReplacements','nodeViewMounts','mapHydrations'].map((key) => [key, number(sample?.metrics?.[key])]));
  return { runIndex: number(runIndex), phase: runIndex === 0 ? 'warmup' : 'sample', metrics,
    compileMs: durations(sample?.compileDurations), applyMs: durations(sample?.applyDurations), idbWriteCount: number(sample?.idbWriteCount) };
}
function summarizeSamples(samples) {
  const sanitized = samples.map((sample,index) => sanitizeSample(sample,index+1));
  const p95s = samples.map((s) => stats([...s.compileDurations, ...s.applyDurations]).p95);
  return { samples: sanitized, compileMs: stats(samples.flatMap((s) => s.compileDurations)),
    applyMs: stats(samples.flatMap((s) => s.applyDurations)), perSampleCombinedP95Ms: p95s,
    medianSampleP95Ms: stats(p95s).median, longestPipelineMs: stats(samples.flatMap((s) => [...s.compileDurations,...s.applyDurations])).longest,
    idbWriteCounts: sanitized.map((s) => s.idbWriteCount), warmupExcluded: true };
}
function provenance(testInfo, browserVersion, viewport, fixturePaths, env = process.env) {
  const repo = path.resolve(__dirname, '../../../../..');
  let checkoutHead = null, checkoutDirty = null;
  try {
    const head = execFileSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8',timeout:2000,stdio:['ignore','pipe','ignore']}).trim();
    if (/^[0-9a-f]{40}$/.test(head)) checkoutHead = head;
    checkoutDirty = Boolean(execFileSync('git',['status','--porcelain','--untracked-files=no'],{cwd:repo,encoding:'utf8',timeout:2000,stdio:['ignore','pipe','ignore']}));
  } catch { /* provenance remains explicitly unavailable */ }
  const claim = (name, length) => new RegExp(`^[0-9a-f]{${length}}$`).test(env[name] || '') ? env[name] : null;
  return {
    phase: ['before','after'].includes(env.OPENMATES_PERF_PHASE) ? env.OPENMATES_PERF_PHASE : 'unspecified',
    frontendModeDeclared: ['vite-dev','production-preview','deployed-production'].includes(env.OPENMATES_PERF_FRONTEND_MODE) ? env.OPENMATES_PERF_FRONTEND_MODE : 'unknown',
    runnerCheckoutHead: checkoutHead, runnerCheckoutDirty: checkoutDirty,
    runtimeSourceCommitClaim: claim('OPENMATES_PERF_RUNTIME_SOURCE_COMMIT',40),
    runtimeAssetInventorySha256Claim: claim('OPENMATES_PERF_RUNTIME_ASSET_INVENTORY_SHA256',64),
    fixtureDataSha256Claim: claim('OPENMATES_PERF_FIXTURE_DATA_SHA256',64),
    runtimeIdentityQualification: 'Runner-supplied claims require matching CI environment/build receipts; checkout identity alone does not attest the served runtime.',
    fixtureSha256: fixturePaths.map((p) => { try { return hash(fs.readFileSync(path.join(repo,p))); } catch { return null; } }),
    browser: ['chromium','webkit','firefox'].includes(testInfo.project.use.browserName) ? testInfo.project.use.browserName : 'unspecified',
    browserVersion: /^[0-9.]{1,60}$/.test(browserVersion || '') ? browserVersion : null,
    viewport: viewport ? { width: number(viewport.width), height: number(viewport.height) } : null,
    mobile: testInfo.project.use.isMobile === true, deviceScaleFactorDeclared: number(testInfo.project.use.deviceScaleFactor),
    cache: 'Not disabled or forcibly cleared; fresh context is not proof of disk/network coldness. Repeated navigations reuse context. Inspect per-run cache/SW observations.',
    network: 'Existing CI/browser configuration unchanged; no bandwidth/CPU shaping added by this patch.',
  };
}
function resourceEvidence(snapshot, navigationOrdinal, declaredMode) {
  declaredMode = ['vite-dev','production-preview','deployed-production'].includes(declaredMode) ? declaredMode : 'unknown';
  // Whitelist every field even when the collector receives an unexpected object.
  const bucketKeys = ['count','transferBytes','encodedBodyBytes','decodedBodyBytes','firstParty','thirdParty','opaqueOrigin','zeroTransferWithBody','allSizesZero','deliveryCacheReported','serviceWorkerIntercepted'];
  return { navigationOrdinal: number(navigationOrdinal), cacheAttempt: navigationOrdinal === 0 ? 'first-navigation-context-cache-uncontrolled' : 'reused-context-cache-uncontrolled-see-scenario-route-role',
    frontendMode: snapshot.devModuleObserved ? 'vite-dev-observed' : declaredMode,
    productionClaimConflictsWithObservedDev: snapshot.devModuleObserved && ['production-preview','deployed-production'].includes(declaredMode),
    totals: Object.fromEntries(['javascript','observedWasmResource','other'].map((kind) => [kind,Object.fromEntries(bucketKeys.map((key) => [key,number(snapshot?.buckets?.[kind]?.[key])]))])),
    navigation: snapshot.navigation ? {...Object.fromEntries(['transferBytes','encodedBodyBytes','decodedBodyBytes'].map((k) => [k,number(snapshot.navigation[k])])), ...Object.fromEntries(['zeroTransferWithBody','allSizesZero','deliveryCacheReported','serviceWorkerIntercepted'].map((k) => [k,snapshot.navigation[k] === true]))} : null,
    totalEntries: number(snapshot.totalEntries), omittedEntries: number(snapshot.omittedEntries),
    capture: { installed: snapshot.capture?.installed === true, requestedCapacity: number(snapshot.capture?.requestedCapacity), bufferFullEvents: number(snapshot.capture?.bufferFullEvents), mayBeIncomplete: snapshot.capture?.installed !== true || number(snapshot.capture?.bufferFullEvents) !== 0 || number(snapshot.omittedEntries) !== 0 },
    usedJSHeapBytes: number(snapshot.usedJSHeapBytes), observedDevice: Object.fromEntries(['pixelRatio','hardwareConcurrency','deviceMemoryGiB'].map((k) => [k,number(snapshot.observedDevice?.[k])])), serviceWorkerControlled: snapshot.serviceWorkerControlled === true,
    limits: ['ResourceTiming sizes may be zero from cache, opaque responses or Timing-Allow-Origin restrictions; zero is not definitive cache proof.',
      'ResourceTiming may discard entries when its buffer fills. Uninstalled capture, buffer-full events or omitted entries make totals lower bounds; event count is not a dropped-entry count.',
      'Observed WASM means resources whose URL pathname ends .wasm, including third-party counters. Zero observed WASM does not rule out inline/embedded/data-url or differently named WASM.',
      'Dev-module bytes are not production bundle/download size. Heap is Chromium-only JS heap when exposed, not RSS/full process memory. WASM initialization, full CPU and essential app flows are unmeasured here.'] };
}
function routeSelectionSha256(value) {
  try { return hash(new URL(value, 'https://synthetic.invalid').pathname); } catch { return null; }
}
function performanceAttachment(evidence) {
  try {
    const body = Buffer.from(JSON.stringify(evidence));
    if (body.length <= 256*1024) return body;
    return Buffer.from(JSON.stringify({schemaVersion:1,status:'unavailable',reason:'sanitized_attachment_size_bound',measurementClaim:false}));
  } catch {
    return Buffer.from(JSON.stringify({schemaVersion:1,status:'unavailable',reason:'sanitized_attachment_encoding_failed',measurementClaim:false}));
  }
}
module.exports = { performanceAttachment, routeSelectionSha256, installResourceTimingCapture, browserResourceSnapshot, stats, sanitizeSample, summarizeSamples, provenance, resourceEvidence };
