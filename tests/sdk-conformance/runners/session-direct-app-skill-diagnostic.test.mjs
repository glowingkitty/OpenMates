/** Pure source/VM tests. No SDK import, peer, network or application execution. */
// contract-test-file: tooling
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {extractAppsDiagnostic,appsDigestCatalog,decodeAppsDigest,digest} from './session-direct-app-skill-diagnostic.mjs';
const source=readFileSync(new URL('./session-direct-app-skill.mjs',import.meta.url),'utf8');
test('Apps labels keep all18 vectors and unchanged assertion/deadline boundaries',()=>{
 const h=extractAppsDiagnostic(source);assert.equal(h.vectors.length,18);assert.equal(new Set(h.vectors).size,18);
 assert.equal((source.match(/assert\./g)||[]).length,21);
 for(const boundary of ["setTimeout(()=>reject(Error('direct fixture deadline')),30000)","for(let i=0;i<500;i++)","await pause(10)","assert.equal(results.length,18)","assert.equal(report.skill_posts,v.expected_skill_posts)","assert.equal(report.downloads,v.expected_downloads)","assert.equal(report.retention_posts,v.expected_retention_posts)","assert.ok(report.auth>=1)","if(peer.exitCode===null&&peer.signalCode===null)","peer.kill('SIGTERM');await bounded(ended)"])assert.ok(source.includes(boundary),boundary);
 assert.match(source,/catch\(error\)\{captureAppsFailure\(error\);throw error;\}finally\{/);
});
test('source-selected import stages and admitted vector are finite; first failure survives cleanup',()=>{
 const h=extractAppsDiagnostic(source);
 for(const stage of ['public_sdk_import'])assert.ok(h.stages.includes(stage));
 h.stage('cookie_run');h.vector('cookie-sync');h.capture({code:'authentication',message:'PRIVATE_BODY'});
 const original=h.failure();h.stage('cleanup_session');h.capture({code:'protocol',message:'PRIVATE_COOKIE'});
 assert.equal(h.failure(),original);assert.equal(original,'apps_diagnostic:cookie_run:cookie-sync:authentication\n');
 for(const stage of h.suiteStages)assert.equal(h.line(stage,'cookie-sync','type').split(':')[2],'none');
 assert.equal(h.line('PRIVATE_STAGE','PRIVATE_VECTOR','PRIVATE_ERROR'),'apps_diagnostic:unclassified:none:unclassified\n');
});
test('error classification reads own fixed code only and never message/name/cause getters',()=>{
 const h=extractAppsDiagnostic(source);let reads=0;const error={};
 for(const key of ['code','message','name','cause'])Object.defineProperty(error,key,{get(){reads++;throw Error('PRIVATE');}});
 assert.equal(h.classify(error),'unclassified');assert.equal(reads,0);
 for(const code of ['ERR_ASSERTION','ERR_MODULE_NOT_FOUND','ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX','authentication','native_binding_unavailable'])assert.notEqual(h.classify({code,message:'PRIVATE_BODY'}),'unclassified');
 assert.equal(h.classify({code:'PRIVATE_UNKNOWN',message:'ERR_MODULE_NOT_FOUND'}),'unclassified');
});
test('finite digest catalog recovers only exact Apps adapter/checker envelope labels',()=>{
 const {helper,entries}=appsDigestCatalog(source);assert.ok(entries.size>1000);
 assert.ok([...entries.keys()].every(key=>Number(key.slice(0,key.indexOf(':')))<=512));
 for(const envelope of ['adapter','checker']){
  const prefix=envelope==='checker'?'Library conformance failed sdk.apps/npm (returncode=1, signal=none): ':'';
  const bytes=Buffer.from(prefix+helper.generic+helper.line('public_sdk_import','none','module_not_found')+(envelope==='checker'?'\n':''));
  const decoded=decodeAppsDigest(source,bytes.length,digest(bytes));assert.equal(decoded.status,'matched');assert.equal(decoded.stage,'public_sdk_import');assert.equal(decoded.envelope,envelope);assert.equal(decoded.attribution,'suite-only');
 }
 assert.deepEqual(decodeAppsDigest(source,1316,'141fd083c9e2a21c10dc28c90394209188feda5cc3741e7c56f1780af75531b9'),{status:'unmatched'},'historical SDK stderr receives no invented attribution');
 assert.deepEqual(decodeAppsDigest(source,12,digest('PRIVATE_BODY')),{status:'unmatched'});
 assert.throws(()=>decodeAppsDigest(source,-1,'a'.repeat(64)));assert.throws(()=>decodeAppsDigest(source,1,'PRIVATE_HASH'));
});
test('decoder refuses missing/repeated source boundaries and never evaluates runner body',()=>{
 assert.throws(()=>extractAppsDiagnostic(source.replace('// BEGIN CLOSED APPS DIAGNOSTIC','// MISSING')));
 assert.throws(()=>extractAppsDiagnostic(source+'\n// END CLOSED APPS DIAGNOSTIC'));
 assert.equal(extractAppsDiagnostic(source+'\nthrow Error("SDK_MUST_NOT_RUN")').vectors.length,18);
});

test('Apps conformance imports the existing compiled public headless entry with all3 required exports',()=>{
 const packageBase=new URL('../../../frontend/packages/openmates-cli/',import.meta.url);
 const packageJson=JSON.parse(readFileSync(new URL('package.json',packageBase),'utf8'));
 assert.equal(packageJson.exports['./sdk'].default,'./dist/sdk-entry.js');
 assert.match(packageJson.scripts['build:sdk'],/tsup src\/sdk-entry\.ts/);
 const entry=readFileSync(new URL('src/sdk-entry.ts',packageBase),'utf8');
 assert.ok(entry.includes('export * from "./sdk.js"'));assert.ok(entry.includes('export * from "./sdkSession.js"'));
 const session=readFileSync(new URL('src/sdkSession.ts',packageBase),'utf8'),api=readFileSync(new URL('src/sdk.ts',packageBase),'utf8');
 assert.match(session,/export class SessionClient\b/);assert.match(session,/export class SessionClientError\b/);assert.match(api,/export class OpenMates\b/);
 assert.ok(source.includes("({SessionClient,SessionClientError,OpenMates}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js'))"));
 assert.ok(!source.includes('loader.mjs'));assert.ok(!source.includes("from 'node:module'"));
 assert.ok(!source.includes('/src/sdkSession.ts'));assert.ok(!source.includes('/src/sdk.ts'));assert.ok(!source.includes('transform-types'));
});
test('the removed source-loader route is resolve-only and the SDK sources strip-load under Node type stripping',()=>{
 const base=new URL('../../../frontend/packages/openmates-cli/',import.meta.url);
 const loader=readFileSync(new URL('tests/loader.mjs',base),'utf8');assert.match(loader,/export async function resolve\(/);assert.ok(!loader.includes('export async function load('));assert.ok(!loader.includes('transpile'));
 const session=readFileSync(new URL('src/sdkSession.ts',base),'utf8'),essential=readFileSync(new URL('src/sdkEssential.ts',base),'utf8');
 assert.ok(session.includes('from "./sdkEssential.js"'));assert.ok(essential.includes("from './sdkStartupSync.js'"));
 const startup=readFileSync(new URL('src/sdkStartupSync.ts',base),'utf8');
 // Parameter properties were removed so Node 22+/24 strip-only loading works.
 assert.doesNotThrow(()=>stripTypeScriptTypes(startup,{mode:'strip'}));
 assert.doesNotThrow(()=>stripTypeScriptTypes(readFileSync(new URL('src/sdkMetadataEphemeral.ts',base),'utf8'),{mode:'strip'}));
});

test('report and cleanup retain only the live admitted vector until awaited runVector finally settles',()=>{
 const stages=['peer_report','peer_report_assert','cleanup_release','cleanup_session','cleanup_peer'];
 for(const stage of stages){
  const h=extractAppsDiagnostic(source);h.vector('cookie-sync');h.stage(stage);
  assert.equal(h.line(stage,'cookie-sync','assertion'),'apps_diagnostic:'+stage+':cookie-sync:assertion\n');
  h.capture({code:'ERR_ASSERTION',message:'PRIVATE_ORIGINAL'});const original=h.failure();
  for(const cleanup of stages.slice(2)){h.stage(cleanup);h.capture({code:'protocol',message:'PRIVATE_CLEANUP'});}
  assert.equal(h.failure(),original,'later cleanup never replaces the first live-vector failure');
  for(const later of stages){const reset=extractAppsDiagnostic(source);reset.vector('cookie-sync');reset.vector('none');reset.stage(later);reset.capture({code:'ERR_ASSERTION'});assert.equal(reset.failure(),'apps_diagnostic:'+later+':none:assertion\n');}
  for(const global of h.suiteStages){const globalCase=extractAppsDiagnostic(source);globalCase.vector('cookie-sync');globalCase.stage(global);globalCase.capture({code:'ERR_ASSERTION'});assert.equal(globalCase.failure(),'apps_diagnostic:'+global+':none:assertion\n');}
 }
 // runVector's existing finally remains inside its awaited promise; the source
 // reset cannot run before report/session/peer cleanup has returned.
 assert.match(source,/results\.push\(await bounded\(runVector\(suite,vector,fixture\)\)\);appsVector='none';/);
 assert.match(source,/captureAppsFailure\(error\);throw error;\}finally\{\n  try\{appsStage='cleanup_release'/);
 assert.ok(source.indexOf("appsStage='cleanup_peer'")<source.indexOf('async function main()'));
});
