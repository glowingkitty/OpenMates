// contract-test: supporting surface=gui.web assertions=sdk.web.before-after-performance
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { installResourceTimingCapture, browserResourceSnapshot, resourceEvidence, sanitizeSample, summarizeSamples, stats, provenance, routeSelectionSha256, performanceAttachment } = require('./performance-evidence.cjs');
test('real in-page collector drops every URL/query and distinguishes JS, third-party wasm and opaque/cache observations', () => {
  const resources = [
    {name:'https://app.example/@vite/client?PRIVATE_TOKEN',initiatorType:'script',transferSize:120,encodedBodySize:100,decodedBodySize:300},
    {name:'https://cdn.example/crypto.wasm?PRIVATE_VALUE',transferSize:0,encodedBodySize:80,decodedBodySize:100,deliveryType:'cache'},
    {name:'https://app.example/api/private-account?PRIVATE_EMAIL',transferSize:0,encodedBodySize:0,decodedBodySize:0,workerStart:1},
    {name:'data:application/wasm;base64,PRIVATE_BODY',transferSize:0,encodedBodySize:12,decodedBodySize:12},
  ];
  const context = {URL,location:{href:'https://app.example/',origin:'https://app.example'},navigator:{serviceWorker:{controller:{}}},performance:{getEntriesByType:(kind) => kind==='resource'?resources:[{transferSize:200,encodedBodySize:160,decodedBodySize:500,workerStart:0}],memory:undefined}};
  const snapshot = vm.runInNewContext(`(${browserResourceSnapshot.toString()})()`,context);
  const output = resourceEvidence(snapshot,0,'production-preview');
  assert.equal(output.frontendMode,'vite-dev-observed');assert.equal(output.productionClaimConflictsWithObservedDev,true);
  assert.equal(output.totals.javascript.transferBytes,120);assert.equal(output.totals.observedWasmResource.thirdParty,1);assert.equal(output.totals.observedWasmResource.deliveryCacheReported,1);
  assert.equal(output.totals.other.opaqueOrigin,1);assert.equal(output.totals.other.allSizesZero,1);assert.equal(output.totals.other.serviceWorkerIntercepted,1);
  assert.equal(output.usedJSHeapBytes,null);assert.equal(output.serviceWorkerControlled,true);
  assert(!JSON.stringify(output).includes('PRIVATE'));assert(!JSON.stringify(output).includes('app.example'));
});
test('sanitizer rejects private extras/nonfinite values, reports truncation and preserves full nearest-rank summary', () => {
  const durations=Array.from({length:600},(_,i) => i+1);
  const sample={metrics:{chunks:50,flushes:20,nodeViewMounts:2,mapHydrations:1,fullReplacements:0,privateText:'PRIVATE'},compileDurations:durations,applyDurations:[NaN,Infinity,-1,'PRIVATE'],idbWriteCount:0,privateText:'PRIVATE'};
  const cleaned=sanitizeSample(sample,1);assert.equal(cleaned.compileMs.values.length,512);assert.equal(cleaned.compileMs.omittedValues,88);assert.equal(cleaned.compileMs.p95,570);assert.equal(cleaned.applyMs.invalidCount,4);assert(!JSON.stringify(cleaned).includes('PRIVATE'));
  const summary=summarizeSamples([sample,{...sample,compileDurations:[2],applyDurations:[3]},{...sample,compileDurations:[4],applyDurations:[5]}]);assert.deepEqual(summary.perSampleCombinedP95Ms,[570,3,5]);assert.equal(summary.medianSampleP95Ms,5);assert.equal(summary.longestPipelineMs,600);assert.deepEqual(summary.idbWriteCounts,[0,0,0]);assert.equal(stats([]).p95,null);
});
test('untrusted mode and provenance environment values never become raw evidence', () => {
  const p=provenance({project:{use:{browserName:'chromium'}}},'124.0.1',{width:1200,height:800},[],{OPENMATES_PERF_PHASE:'PRIVATE',OPENMATES_PERF_FRONTEND_MODE:'PRIVATE',OPENMATES_PERF_RUNTIME_SOURCE_COMMIT:'PRIVATE',OPENMATES_PERF_RUNTIME_ASSET_INVENTORY_SHA256:'PRIVATE'});
  assert.equal(p.phase,'unspecified');assert.equal(p.frontendModeDeclared,'unknown');assert.equal(p.runtimeSourceCommitClaim,null);assert.equal(p.runtimeAssetInventorySha256Claim,null);assert(!JSON.stringify(p).includes('PRIVATE'));
  const r=resourceEvidence({buckets:{},devModuleObserved:false,totalEntries:0,omittedEntries:0,navigation:null},0,'PRIVATE');assert.equal(r.frontendMode,'unknown');assert(!JSON.stringify(r).includes('PRIVATE'));
});
test('resource cap is explicit and zero wasm resources never means no embedded WASM', () => {
  const resource={name:'https://app.example/a.js',transferSize:10,encodedBodySize:5,decodedBodySize:20};
  const snapshot=vm.runInNewContext(`(${browserResourceSnapshot.toString()})()`,{URL,location:{href:'https://app.example/',origin:'https://app.example'},navigator:{},performance:{getEntriesByType:(k)=>k==='resource'?Array(4100).fill(resource):[]}});
  assert.equal(snapshot.totalEntries,4100);assert.equal(snapshot.omittedEntries,4);const evidence=resourceEvidence(snapshot,1,'unknown');assert.equal(evidence.totals.observedWasmResource.count,0);assert(evidence.limits.some((v)=>v.includes('does not rule out inline')));assert(JSON.stringify(evidence).length<10000);
});

test('pre-navigation capture avoids the default 250-entry truncation and reports bounded saturation', () => {
  let capacity=250;
  const entries=[], listeners=new Map();
  const performance={
    setResourceTimingBufferSize:(value)=>{capacity=value;},
    addEventListener:(name,listener)=>listeners.set(name,listener),
    getEntriesByType:(kind)=>kind==='resource'?entries:[],
  };
  const context=vm.createContext({URL,location:{href:'https://app.example/',origin:'https://app.example'},navigator:{},performance});
  vm.runInContext(`(${installResourceTimingCapture.toString()})()`,context);
  assert.equal(capacity,4096);
  // A second initialization must not erase an already-observed buffer-full event.
  const add=()=>{if(entries.length<capacity)entries.push({name:'https://app.example/PRIVATE.js',transferSize:10});else listeners.get('resourcetimingbufferfull')();};
  for(let i=0;i<350;i++)add();
  let output=resourceEvidence(vm.runInContext(`(${browserResourceSnapshot.toString()})()`,context),0,'production-preview');
  assert.equal(output.totalEntries,350);assert.equal(output.capture.mayBeIncomplete,false);
  for(let i=350;i<4100;i++)add();
  vm.runInContext(`(${installResourceTimingCapture.toString()})()`,context);
  output=resourceEvidence(vm.runInContext(`(${browserResourceSnapshot.toString()})()`,context),0,'production-preview');
  assert.equal(output.totalEntries,4096);assert.equal(output.capture.bufferFullEvents,4);assert.equal(output.capture.mayBeIncomplete,true);
  assert(!JSON.stringify(output).includes('PRIVATE'));assert(!JSON.stringify(output).includes('app.example'));
});

test('250 observed entries with no installed capture cannot imply complete resource totals', () => {
  const snapshot=vm.runInNewContext(`(${browserResourceSnapshot.toString()})()`,{URL,location:{href:'https://app.example/',origin:'https://app.example'},navigator:{},performance:{getEntriesByType:(kind)=>kind==='resource'?Array(250).fill({name:'https://app.example/a.js'}):[]}});
  const output=resourceEvidence(snapshot,0,'production-preview');
  assert.equal(output.omittedEntries,0);assert.equal(output.capture.installed,false);assert.equal(output.capture.bufferFullEvents,null);assert.equal(output.capture.mayBeIncomplete,true);
});

test('unsupported capture APIs remain explicitly unverified without exporting exceptions or private extras', () => {
  const context=vm.createContext({performance:{setResourceTimingBufferSize:()=>{throw new Error('PRIVATE');}}});
  vm.runInContext(`(${installResourceTimingCapture.toString()})()`,context);
  const capture=context.__openmatesResourceTimingCaptureV1;
  assert.equal(capture.installed,false);
  const output=resourceEvidence({buckets:{},totalEntries:0,omittedEntries:0,capture:{...capture,private:'PRIVATE'}},0,'production-preview');
  assert.equal(output.capture.mayBeIncomplete,true);assert(!JSON.stringify(output).includes('PRIVATE'));
});

test('route comparison hashes exclude private query/origin and cannot return raw paths', () => {
  assert.equal(routeSelectionSha256('https://first.invalid/docs/synthetic?PRIVATE_TOKEN'),routeSelectionSha256('https://other.invalid/docs/synthetic?OTHER'));
  assert.match(routeSelectionSha256('/docs/synthetic?PRIVATE'),/^[0-9a-f]{64}$/);
  assert.notEqual(routeSelectionSha256('/docs/one'),routeSelectionSha256('/docs/two'));
});

test('attachment bound returns explicit unavailable rather than exporting oversized or unserializable evidence', () => {
  const oversized=JSON.parse(performanceAttachment({synthetic:'PRIVATE'.repeat(50000)}));
  assert.equal(oversized.status,'unavailable');assert.equal(oversized.measurementClaim,false);assert(!JSON.stringify(oversized).includes('PRIVATE'));
  const cyclic={};cyclic.self=cyclic;assert.equal(JSON.parse(performanceAttachment(cyclic)).reason,'sanitized_attachment_encoding_failed');
});
