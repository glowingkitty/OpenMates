'use strict';
/** Test-only Chromium HTTP-cache controls and sanitized local owned-process endpoint evidence. */
const fs = require('node:fs');
const MAX_PROCESSES = 128, MAX_ANCESTORS = 16, COMMAND_TIMEOUT_MS = 2000;
const finite = (v) => Number.isFinite(v) && v >= 0;
function procIdentity(pid, reader = fs, uid = process.getuid?.()) {
  if (!Number.isSafeInteger(pid) || pid <= 1 || uid === undefined) throw new Error('proc_unavailable');
  const readStat = () => {
    const raw = reader.readFileSync(`/proc/${pid}/stat`, 'utf8');
    if (raw.length > 8192) throw new Error('proc_bound');
    const fields = raw.slice(raw.lastIndexOf(') ') + 2).trim().split(/\s+/);
    if (!/^\d+$/.test(fields[19] || '') || !Number.isSafeInteger(Number(fields[1]))) throw new Error('proc_shape');
    return { birth: fields[19], ppid: Number(fields[1]) };
  };
  const first = readStat(), owner = reader.statSync(`/proc/${pid}`).uid;
  const status = reader.readFileSync(`/proc/${pid}/status`, 'utf8');
  if (status.length > 65536 || owner !== uid) throw new Error('proc_owner');
  const rss = /^VmRSS:\s+(\d+)\s+kB$/m.exec(status);
  const last = readStat();
  if (first.birth !== last.birth || first.ppid !== last.ppid || reader.statSync(`/proc/${pid}`).uid !== uid || !rss) throw new Error('proc_changed');
  const rssBytes = Number(rss[1]) * 1024;
  if (!Number.isSafeInteger(rssBytes)) throw new Error('proc_rss');
  return { pid, ...first, uid: owner, rssBytes };
}
function descendsFrom(pid, ancestor, readIdentity) {
  const seen = new Set();
  for (let i = 0; i < MAX_ANCESTORS && pid > 1 && !seen.has(pid); i++) {
    if (pid === ancestor) return true;
    seen.add(pid); pid = readIdentity(pid).ppid;
  }
  return false;
}
function sanitizeWindow(before, after) {
  const stable = after.rows.filter((row) => before.rows.some((old) => old.pid === row.pid && old.birth === row.birth));
  let cpuMs = 0, invalidCpuPairs = 0;
  for (const row of stable) {
    const old = before.rows.find((item) => item.pid === row.pid && item.birth === row.birth);
    const delta = row.cpuTime - old.cpuTime;
    if (!finite(delta)) invalidCpuPairs++;
    else cpuMs += delta * 1000;
  }
  const snapshot = (sample) => ({ reportedVerifiedProcessCount: sample.rows.length, summedReportedProcessRssBytes: sample.rows.reduce((sum, row) => sum + row.rssBytes, 0) });
  return {
    available: true, stableReportedProcessCpuMs: invalidCpuPairs ? null : cpuMs,
    stableProcessCount: stable.length, invalidCpuPairs,
    newlyReportedOrReplacedProcessCount: after.rows.length - stable.length,
    noLongerReportedOrReplacedProcessCount: before.rows.length - stable.length,
    before: snapshot(before), after: snapshot(after),
    elapsedBetweenSnapshotStartsMs: after.startedMs - before.startedMs,
    beforeSnapshotDurationMs: before.finishedMs - before.startedMs,
    afterSnapshotDurationMs: after.finishedMs - after.startedMs,
    scope: 'Verified local same-UID processes reported by this sole-context Chromium CDP session; CPU deltas only for matching PID+birth endpoints.',
    limitations: ['CPU is cumulative CDP all-thread CPU seconds differenced for stable reported processes; it includes browser/automation/sampler work and is not per-page CPU or utilization.', 'Processes born and exited between endpoint lists are unobserved. Churn is counted, not estimated. This is never a complete browser CPU claim.', 'RSS is summed per-process resident memory at each sampled endpoint, can double-count shared pages and excludes unreported/exited processes. It is not peak RSS, PSS, unique physical RAM or page-only RAM.', 'JS heap and WASM linear memory are separate; neither is inferred from RSS. WASM linear memory is unavailable without runtime hooks.', 'Endpoint collection is sequential and non-atomic; diagnostic overhead and scheduling are included. No continuous process monitor or global procfs scan is used.'],
  };
}
// Acceptance is about valid endpoints within the declared partial process scope,
// never completeness of all browser lifetime CPU, physical RAM or KDF work.
function assessObservation({ begin, end, kind, sameRoute }) {
  const reject = (reason) => ({ accepted: false, reason });
  if (!['login', 'reload'].includes(kind)) return reject('invalid_observation_kind');
  if (begin?.available !== true) return reject('begin_endpoint_unavailable');
  if (end?.available !== true) return reject('end_endpoint_unavailable');
  if (end.invalidCpuPairs !== 0) return reject('invalid_cpu_pairs');
  if (!finite(end.stableReportedProcessCpuMs)) return reject('invalid_cpu_delta');
  if (!Number.isSafeInteger(end.stableProcessCount) || end.stableProcessCount < 1) return reject('no_stable_processes');
  for (const endpoint of [end.before, end.after]) {
    if (!Number.isSafeInteger(endpoint?.reportedVerifiedProcessCount) || endpoint.reportedVerifiedProcessCount < end.stableProcessCount
      || !Number.isSafeInteger(endpoint?.summedReportedProcessRssBytes) || endpoint.summedReportedProcessRssBytes < 0) return reject('invalid_process_memory_endpoint');
  }
  if (kind === 'reload' && sameRoute !== true) return reject('route_mismatch');
  return { accepted: true, reason: 'valid_endpoints_within_declared_partial_process_scope' };
}

async function bounded(operation) {
  let timer;
  try { return await Promise.race([Promise.resolve().then(operation), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('cdp_timeout')), COMMAND_TIMEOUT_MS); })]); }
  finally { clearTimeout(timer); }
}
async function createBrowserProcessEvidence(page, options = {}) {
  const browser = page.context().browser();
  const readIdentity = options.readIdentity || ((pid) => procIdentity(pid));
  const ownerPid = options.ownerPid || process.pid;
  let browserSession, pageSession, before = null;
  const unavailable = () => ({ available: false, reason: 'local_owned_chromium_process_metrics_unavailable' });
  const soleContext = () => browser && browser.contexts().length === 1 && browser.contexts()[0] === page.context() && page.context().pages().length === 1;
  async function snapshot() {
    if (!soleContext()) throw new Error('sole_context_required');
    const startedMs = Date.now(), owner = readIdentity(ownerPid);
    const result = await bounded(() => browserSession.send('SystemInfo.getProcessInfo'));
    if (!Array.isArray(result.processInfo) || !result.processInfo.length || result.processInfo.length > MAX_PROCESSES) throw new Error('process_list_bound');
    const roots = result.processInfo.filter((row) => row.type === 'browser');
    if (roots.length !== 1 || !descendsFrom(roots[0].id, ownerPid, readIdentity)) throw new Error('local_browser_required');
    const root = readIdentity(roots[0].id), ids = new Set();
    const rows = result.processInfo.map((info) => {
      if (!finite(info.cpuTime) || ids.has(info.id)) throw new Error('process_shape');
      ids.add(info.id);
      const identity = readIdentity(info.id);
      if (identity.uid !== owner.uid || !descendsFrom(info.id, root.pid, readIdentity)) throw new Error('reported_process_owner');
      return { ...identity, cpuTime: info.cpuTime };
    });
    const checkedRoot = readIdentity(root.pid), checkedOwner = readIdentity(ownerPid);
    if (checkedRoot.birth !== root.birth || checkedOwner.birth !== owner.birth) throw new Error('owner_changed');
    return { rows, startedMs, finishedMs: Date.now() };
  }
  try {
    if (!soleContext() || typeof browser.newBrowserCDPSession !== 'function') throw new Error('unsupported');
    browserSession = await bounded(() => browser.newBrowserCDPSession());
    pageSession = await bounded(() => page.context().newCDPSession(page));
    // Verify local ownership before any HTTP-cache mutation.
    await snapshot();
  } catch {
    await browserSession?.detach().catch(() => {});
    await pageSession?.detach().catch(() => {});
    return { available: false, prepareHttpCold: async () => unavailable(), begin: async () => unavailable(), end: async () => unavailable(), close: async () => {} };
  }
  return {
    available: true,
    async prepareHttpCold() {
      try {
        await snapshot();
        await bounded(() => pageSession.send('Network.enable'));
        await bounded(() => pageSession.send('Network.setBypassServiceWorker', { bypass: true }));
        await bounded(() => pageSession.send('Network.setCacheDisabled', { cacheDisabled: false }));
        await bounded(() => pageSession.send('Network.clearBrowserCache'));
        return { available: true, definition: 'Browser HTTP cache cleared once after login; cache enabled for cold fill and two same-route warm reload attempts; service-worker bypass held true for all samples. Auth/IDB/application data untouched. Warm cache hits are observations, not guaranteed.' };
      } catch { return { available: false, reason: 'http_cache_control_unavailable' }; }
    },
    async begin() { try { before = await snapshot(); return { available: true }; } catch { before = null; return unavailable(); } },
    async end() {
      const initial = before; before = null;
      if (!initial) return unavailable();
      try { return sanitizeWindow(initial, await snapshot()); } catch { return unavailable(); }
    },
    async close() {
      await bounded(() => pageSession.send('Network.setBypassServiceWorker', { bypass: false })).catch(() => {});
      await pageSession.detach().catch(() => {});
      await browserSession.detach().catch(() => {});
    },
  };
}
module.exports = { procIdentity, descendsFrom, sanitizeWindow, assessObservation, createBrowserProcessEvidence };
