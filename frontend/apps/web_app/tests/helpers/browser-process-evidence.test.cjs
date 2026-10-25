'use strict';
/** Inert coverage for process ownership, sanitized metrics and measurement acceptance; no browser is launched. */
const test = require('node:test');
const assert = require('node:assert/strict');
const { procIdentity, descendsFrom, sanitizeWindow, assessObservation, createBrowserProcessEvidence } = require('./browser-process-evidence.cjs');
function identity(pid, ppid, birth = '42', rssBytes = 1024) { return { pid, ppid, birth, rssBytes, uid: 1000 }; }
test('proc identity parses bounded RSS with identity recheck, including parentheses in names', () => {
  const fields = Array(24).fill('0'); fields[1] = '21'; fields[19] = '1234';
  const reader = { readFileSync: (name) => name.endsWith('/stat') ? `22 (name ) with spaces) ${fields.join(' ')}` : 'Name:\tSECRET_COMMAND\nVmRSS:\t17 kB\n', statSync: () => ({ uid: 1000 }) };
  assert.deepEqual(procIdentity(22, reader, 1000), identity(22,21,'1234',17408));
  assert.throws(() => procIdentity(22, reader, 1001));
  let calls = 0;
  assert.throws(() => procIdentity(22, { ...reader, readFileSync(name) { const value = reader.readFileSync(name); return name.endsWith('/stat') && ++calls > 1 ? value.replace('1234','1235') : value; } }, 1000));
});
test('ownership ancestry is bounded and rejects loops and unrelated processes', () => {
  const rows = new Map([[20,identity(20,10)],[10,identity(10,5)],[30,identity(30,30)]]);
  assert.equal(descendsFrom(20,10,(pid) => rows.get(pid)),true);
  assert.equal(descendsFrom(30,10,(pid) => rows.get(pid)),false);
});
test('CPU differences use matching births; output has no process identifiers or raw data', () => {
  const before = { startedMs: 10, finishedMs: 12, rows: [{ ...identity(20,10), cpuTime: 1 },{ ...identity(21,20), cpuTime: 2 }] };
  const after = { startedMs: 30, finishedMs: 33, rows: [{ ...identity(20,10), cpuTime: 1.125 },{ ...identity(21,20,'43'), cpuTime: 9 }] };
  const output = sanitizeWindow(before,after);
  assert.equal(output.stableReportedProcessCpuMs,125); assert.equal(output.stableProcessCount,1);
  assert.equal(output.newlyReportedOrReplacedProcessCount,1); assert.equal(output.noLongerReportedOrReplacedProcessCount,1);
  assert.equal(output.after.summedReportedProcessRssBytes,2048);
  assert.equal(Object.hasOwn(output,'rows'),false); assert.equal(JSON.stringify(output).includes('"pid"'),false);
  assert.equal(JSON.stringify(output).includes('"birth"'),false);
  after.rows[0].cpuTime = 0.5; assert.equal(sanitizeWindow(before,after).stableReportedProcessCpuMs,null);
});
function harness({ unrelated = false, duplicate = false, multipleContexts = false } = {}) {
  const commands = [], rows = new Map([[10,identity(10,5)],[20,identity(20,unrelated ? 5 : 10)],[21,identity(21,20)]]);
  let cpuTime = 1, failCdp = false, failProc = false;
  const browserSession = { async send(command) {
    if (failCdp) throw new Error('synthetic_cdp_unavailable');
    commands.push(command);
    const info = [{ type: 'browser', id: 20, cpuTime },{ type: 'renderer', id: 21, cpuTime }];
    if (duplicate) info.push(info[0]);
    return { processInfo: info };
  }, async detach() {} };
  const pageSession = { async send(command,args) { commands.push([command,args]); }, async detach() {} };
  const context = { browser: () => browser, pages: () => [page], newCDPSession: async () => pageSession };
  const browser = { contexts: () => multipleContexts ? [context,{}] : [context], newBrowserCDPSession: async () => browserSession };
  const page = { context: () => context };
  return { page, commands, options: { ownerPid:10, readIdentity: (pid) => { if (failProc) throw new Error('synthetic_proc_unavailable'); return rows.get(pid); } }, bump: () => { cpuTime += 0.1; }, failCdp: () => { failCdp = true; }, failProc: () => { failProc = true; } };
}
test('verified sole browser controls only HTTP cache and SW bypass, samples process CPU/RSS', async () => {
  const h = harness(), meter = await createBrowserProcessEvidence(h.page,h.options);
  assert.equal(meter.available,true); assert.equal((await meter.prepareHttpCold()).available,true);
  await meter.begin(); h.bump(); const result = await meter.end();
  assert.ok(Math.abs(result.stableReportedProcessCpuMs - 200) < 1e-6);
  const mutations = h.commands.filter(Array.isArray).map(([name]) => name);
  assert.deepEqual(mutations,['Network.enable','Network.setBypassServiceWorker','Network.setCacheDisabled','Network.clearBrowserCache']);
  assert.equal(JSON.stringify(h.commands).includes('Cookie'),false);
  await meter.close();
});
test('unowned, ambiguous process lists or shared contexts never clear caches', async () => {
  for (const config of [{ unrelated:true },{ duplicate:true },{ multipleContexts:true }]) {
    const h = harness(config), meter = await createBrowserProcessEvidence(h.page,h.options);
    assert.equal(meter.available,false); assert.equal((await meter.prepareHttpCold()).available,false);
    assert.equal(h.commands.some((entry) => Array.isArray(entry)),false);
  }
});

test('post-admission CDP or procfs failure prevents observation acceptance', async () => {
  const cdp = harness(), first = await createBrowserProcessEvidence(cdp.page,cdp.options);
  assert.equal(first.available,true); cdp.failCdp();
  const failedBegin = await first.begin();
  assert.deepEqual(assessObservation({ begin: failedBegin, end: await first.end(), kind: 'reload', sameRoute: true }), { accepted: false, reason: 'begin_endpoint_unavailable' });
  await first.close();
  const proc = harness(), second = await createBrowserProcessEvidence(proc.page,proc.options);
  assert.equal(second.available,true); const begin = await second.begin(); proc.failProc();
  assert.deepEqual(assessObservation({ begin, end: await second.end(), kind: 'reload', sameRoute: true }), { accepted: false, reason: 'end_endpoint_unavailable' });
  await second.close();
});
function validObservation() {
  const sample = { startedMs: 1, finishedMs: 2, rows: [{ ...identity(20,10), cpuTime: 1 }] };
  return sanitizeWindow(sample,{ ...sample, startedMs: 3, finishedMs: 4 });
}
test('invalid CPU pairs or missing memory endpoints prevent acceptance', () => {
  const end = validObservation();
  assert.equal(assessObservation({ begin: { available: true }, end, kind: 'login' }).accepted,true);
  assert.deepEqual(assessObservation({ begin: { available: true }, end: { ...end, invalidCpuPairs: 1, stableReportedProcessCpuMs: null }, kind: 'login' }), { accepted: false, reason: 'invalid_cpu_pairs' });
  assert.equal(assessObservation({ begin: { available: true }, end: { ...end, stableReportedProcessCpuMs: NaN }, kind: 'login' }).accepted,false);
  assert.equal(assessObservation({ begin: { available: true }, end: { ...end, after: null }, kind: 'login' }).accepted,false);
});
test('exact route match is mandatory for accepting reload samples', () => {
  const input = { begin: { available: true }, end: validObservation(), kind: 'reload' };
  assert.deepEqual(assessObservation({ ...input, sameRoute: false }), { accepted: false, reason: 'route_mismatch' });
  assert.equal(assessObservation(input).accepted,false);
  assert.equal(assessObservation({ ...input, sameRoute: true }).accepted,true);
});
