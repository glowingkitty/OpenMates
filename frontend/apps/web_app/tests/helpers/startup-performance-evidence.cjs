'use strict';
const { performanceAttachment, provenance, browserResourceSnapshot, resourceEvidence, installResourceTimingCapture } = require('./performance-evidence.cjs');
const TYPES = new Set(['server_capabilities', 'phase_1b_chat_content_ready', 'phase_2_last_20_chats_ready', 'background_message_sync', 'sync_status_response', 'sync_metadata_chats_response', 'sync_metadata_chats_error', 'request_chat_content_batch']);
const MAX_TASKS = 4096;
function createFrameSummary() {
  return { frames: 0, utf8ApplicationBytes: 0, nonJsonFrames: 0, types: {}, shapes: { chats: 0, messages: 0, embeds: 0, embedKeys: 0, codeOutputs: 0, notebookOutputs: 0, wrappers: 0 }, firstPhase1bAtMs: null, firstPhase2AtMs: null };
}
// Called by existing frame listeners. Never store payloads, arbitrary type names,
// IDs, values, keys, cursor fields or exception strings in evidence.
function recordFrame(summary, raw, parsed, now = Date.now()) {
  summary.frames++;
  summary.utf8ApplicationBytes += Buffer.isBuffer(raw) ? raw.length : Buffer.byteLength(String(raw), 'utf8');
  if (!parsed || typeof parsed !== 'object') { summary.nonJsonFrames++; return; }
  const type = TYPES.has(parsed.type || parsed.event) ? (parsed.type || parsed.event) : 'other';
  summary.types[type] = (summary.types[type] || 0) + 1;
  const p = parsed.payload ?? parsed;
  if (type === 'phase_1b_chat_content_ready' && summary.firstPhase1bAtMs === null) summary.firstPhase1bAtMs = now;
  if (type === 'phase_2_last_20_chats_ready' && summary.firstPhase2AtMs === null) summary.firstPhase2AtMs = now;
  if (!['phase_1b_chat_content_ready', 'phase_2_last_20_chats_ready'].includes(type)) return;
  const count = (value) => Array.isArray(value) ? value.length : 0;
  summary.shapes.chats += count(p.chats);
  for (const chat of Array.isArray(p.chats) ? p.chats : []) summary.shapes.messages += count(chat?.messages);
  for (const [key, field] of Object.entries({ embeds: 'embeds', embedKeys: 'embed_keys', codeOutputs: 'code_run_outputs', notebookOutputs: 'notebook_run_outputs', wrappers: 'chat_key_wrappers' })) summary.shapes[key] += count(p[field]);
}
function installBrowserCollector() {
  const state = { supported: false, tasks: [], omitted: 0 };
  globalThis.__startupPerfCounts = state;
  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.duration < 50) continue;
        if (state.tasks.length < 4096) state.tasks.push({ startEpochMs: performance.timeOrigin + entry.startTime, durationMs: entry.duration });
        else state.omitted++;
      }
    });
    observer.observe({ type: 'longtask', buffered: true });
    state.supported = PerformanceObserver.supportedEntryTypes?.includes('longtask') === true;
  } catch { /* Explicitly unsupported, not a zero-task claim. */ }
}
async function persistedCounts(page) {
  return page.evaluate(async () => {
    const unavailable = (reason) => ({ available: false, chats: null, messages: null, reason });
    const bounded = (operation) => new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('count_snapshot_timeout')), 2000);
      Promise.resolve().then(operation).then((value) => { clearTimeout(timer); resolve(value); }, (error) => { clearTimeout(timer); reject(error); });
    });
    let db = null;
    try {
      // Listing avoids creating a database; the upgrade handler also aborts the
      // list/open race. Every open/transaction has a bounded unavailable result.
      if (typeof indexedDB.databases !== 'function') return unavailable('database_listing_unsupported');
      if (!(await bounded(() => indexedDB.databases())).some((entry) => entry.name === 'chats_db')) return unavailable('database_absent');
      db = await new Promise((resolve, reject) => {
        let settled = false;
        const request = indexedDB.open('chats_db');
        const fail = () => {
          if (settled) return;
          settled = true; clearTimeout(timer);
          reject(new Error('count_snapshot_open_unavailable'));
        };
        const timer = setTimeout(fail, 2000);
        request.onupgradeneeded = () => {
          // A vanished DB must not be created or upgraded by instrumentation.
          request.transaction?.abort();
          request.result?.close();
          fail();
        };
        request.onblocked = request.onerror = fail;
        request.onsuccess = () => {
          if (settled) { request.result.close(); return; }
          settled = true; clearTimeout(timer); resolve(request.result);
        };
      });
      db.onversionchange = () => db.close();
      if (!['chats','messages'].every((name) => db.objectStoreNames.contains(name))) return unavailable('stores_absent');
      return await new Promise((resolve) => {
        const tx = db.transaction(['chats','messages'], 'readonly');
        let settled = false;
        const finish = (value) => { if (!settled) { settled = true; clearTimeout(timer); resolve(value); } };
        const timer = setTimeout(() => {
          finish(unavailable('transaction_timeout'));
          try { tx.abort(); } catch { /* already completed */ }
          db.close();
        }, 2000);
        const chats = tx.objectStore('chats').count(), messages = tx.objectStore('messages').count();
        tx.oncomplete = () => finish({ available: true, chats: chats.result, messages: messages.result });
        tx.onerror = tx.onabort = () => finish(unavailable('transaction_unavailable'));
      });
    } catch { return unavailable('snapshot_unavailable'); }
    finally { db?.close(); }
  });
}
function longTaskWindow(snapshot, startMs, endMs) {
  const tasks = snapshot?.tasks?.filter((t) => t.startEpochMs >= startMs && t.startEpochMs + t.durationMs <= endMs) || [];
  return { supported: snapshot?.supported === true, count: tasks.length, durationMs: tasks.reduce((sum, t) => sum + t.durationMs, 0), maxDurationMs: tasks.reduce((max, t) => Math.max(max, t.durationMs), 0), omittedDocumentTasks: snapshot?.omitted ?? null, thresholdMs: 50, maxStoredDocumentTasks: MAX_TASKS };
}
async function createStartupEvidence(page) {
  await page.addInitScript(installResourceTimingCapture);
  await page.addInitScript(installBrowserCollector);
  const windows = [], snapshots = [], summary = createFrameSummary();
  let current = null, firstTransportStartMs = null;
  return {
    recordFrame(raw, parsed) {
      const now = Date.now();
      recordFrame(summary, raw, parsed, now);
      if (current) recordFrame(current.received, raw, parsed, now);
    },
    begin(role) { if (!['startup-transport','established-reconnect'].includes(role)) throw new Error('unsupported_window'); current = { role, startMs: Date.now(), received: createFrameSummary() }; if (firstTransportStartMs === null) firstTransportStartMs = current.startMs; },
    async snapshotPhaseReceipts() { snapshots.push({ stage: 'phase-receipts-observed-before-ready-check', counts: await persistedCounts(page) }); },
    async end() {
      const endMs = Date.now();
      const closedWindow = current;
      current = null; // Detach before any awaited diagnostics; late frames are global-only.
      const countSnapshotStartMs = Date.now();
      const counts = await persistedCounts(page);
      const countSnapshotEndMs = Date.now();
      const browser = await page.evaluate(() => globalThis.__startupPerfCounts || null);
      if (closedWindow) {
        const received = { ...closedWindow.received };
        const relative = (stamp) => stamp === null ? null : stamp - closedWindow.startMs;
        const phaseReceiptMs = { phase1b: relative(received.firstPhase1bAtMs), phase2: relative(received.firstPhase2AtMs) };
        delete received.firstPhase1bAtMs; delete received.firstPhase2AtMs;
        windows.push({ role: closedWindow.role, elapsedDefinition: closedWindow.role === 'established-reconnect' ? 'Socket-close automation through existing two-second carousel sampling, replacement-phase wait, readiness checks and runner scheduling; not pure transport-ready latency. phaseReceiptMs separately records frame receipt.' : 'First runner-observed socket through phase wait, login/reminder automation and readiness checks; not pure transport-ready latency. phaseReceiptMs separately records frame receipt.', elapsedMs: endMs - closedWindow.startMs, received, phaseReceiptMs, ...longTaskWindow(browser, closedWindow.startMs, endMs), persistedCountsSnapshot: { stage: 'after-existing-ready-check', startedMsAfterWindowEnd: countSnapshotStartMs - endMs, completedMsAfterWindowEnd: countSnapshotEndMs - endMs, counts } });
      }
      return counts;
    },
    async attach(testInfo) {
      const resources = await page.evaluate(browserResourceSnapshot);
      const relative = (stamp) => stamp === null || firstTransportStartMs === null ? null : stamp - firstTransportStartMs;
      // Phase receipt times are expressed against the first transport window,
      // not persisted completion; login automation can overlap these windows.
      const frameCounts = { ...summary };
      delete frameCounts.firstPhase1bAtMs; delete frameCounts.firstPhase2AtMs;
      await testInfo.attach('startup-performance-evidence', { contentType: 'application/json', body: performanceAttachment({
        schemaVersion: 1, measurementClaim: false, scenario: 'legacy-browser-encrypted-startup-fixture',
        provenance: provenance(testInfo, page.context().browser()?.version(), page.viewportSize(), ['scripts/ci_startup_sync_fixture.mjs', 'frontend/apps/web_app/tests/startup-sync-contract.spec.ts', 'frontend/apps/web_app/tests/helpers/startup-performance-evidence.cjs']),
        fixture: { startupChats: 22, sharedOwnerChats: 1, phase2ExpectedTotalChats: 23, fixturePairing: 'Same isolated runner provisioning required; compare source/data hashes and actual snapshots.' },
        received: frameCounts, countSnapshots: snapshots, phaseReceiptMsFromFirstSocket: { phase1b: relative(summary.firstPhase1bAtMs), phase2: relative(summary.firstPhase2AtMs) }, windows, resources: resourceEvidence(resources, 0, process.env.OPENMATES_PERF_FRONTEND_MODE),
        limitations: ['Resource capture is bounded to 4096 entries and may be incomplete; inspect shared resource evidence buffer-full, omitted and uncaptured status. No full resource snapshot completeness claim.', 'Phase receipt does not prove persistence; count snapshots follow existing waitForChatReady and do not attest every fixture record or completed decryption.', 'Long tasks cover only the current document and tasks starting in each window; cross-process Date.now/performance.timeOrigin alignment is approximate. Tasks crossing the boundary are excluded.', 'Transport window starts at runner-observed socket creation, which is not an authentication-completion timestamp. Elapsed values include overlapping login/reminder automation and runner scheduling; reconnect also includes the existing carousel sampling loop. Count snapshots run after the frozen window endpoint and report their own start/completion offsets.', 'Only JSON frames processed by the existing listeners contribute to runtime counters; non-JSON traffic is not captured by those listeners.', 'Application-frame UTF-8 bytes exclude wire framing/compression/TLS and do not measure wire traffic.', 'Cold/empty-store and warm reload pairing remains unmeasured; no browser cache, authentication store or chat store is cleared.', 'Heap deltas are not recorded; heap is the optional end-of-scenario JS heap from resource evidence. No inference or runtime Rust integration is introduced.']
      }) });
    }
  };
}
module.exports = { createFrameSummary, recordFrame, longTaskWindow, createStartupEvidence, persistedCounts };
