// contract-test-file: tooling
/** Metadata/source boundary only: never import SDK, register loader, spawn or fetch. */
'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{pathToFileURL}=require('node:url');
const RUNNERS=["api-key-drafts.mjs", "npm.mjs", "privacy.mjs", "project-create.mjs", "project-remote-crypto-worker.mjs", "sdk-api-key-embeds-family.mjs", "sdk-api-key-embeds.mjs", "sdk-api-key-history.mjs", "sdk-api-key-wikipedia.mjs", "sdk-embed-version-content.mjs", "session-anonymous.mjs", "session-auth.mjs", "session-drafts.mjs", "session-embed-share.mjs", "session-embed-version-content.mjs", "session-message-window.mjs", "session-plans-workflows.mjs", "session-project-items.mjs", "session-project-sources.mjs", "session-project-task-watch.mjs", "session-recovery.mjs", "session-saved-chat-read.mjs", "session-settings-reminders-read.mjs", "session-work.mjs", "task-order.mjs", "workflow-file-sync.mjs"];
const root=path.resolve(__dirname,'../../..'),packageRoot=path.join(root,'frontend/packages/openmates-cli');
const manifest=JSON.parse(fs.readFileSync(path.join(packageRoot,'package.json'),'utf8'));
function runtimeExports(filename,seen=new Set()){
 if(seen.has(filename))return new Set();seen.add(filename);
 const source=fs.readFileSync(filename,'utf8'),names=new Set();
 for(const match of source.matchAll(/export\s+(?:async\s+)?(?:class|function|const|let|var|enum)\s+(\w+)/g))names.add(match[1]);
 for(const match of source.matchAll(/export\s*\{([^}]+)\}/g))for(const item of match[1].split(',')){
  const value=item.trim();if(value&&!value.startsWith('type '))names.add(value.split(/\s+as\s+/).pop());
 }
 for(const match of source.matchAll(/export\s*\*\s*from\s*["'](\.[^"']+)["']/g)){
  const next=path.resolve(path.dirname(filename),match[1].replace(/\.js$/,'.ts'));
  for(const name of runtimeExports(next,seen))names.add(name);
 }
 return names;
}
const publicExports=new Map([['sdk-entry.js',runtimeExports(path.join(packageRoot,'src/sdk-entry.ts'))],['sdk-session-v1-entry.js',runtimeExports(path.join(packageRoot,'src/sdk-session-v1-entry.ts'))]]);
function inspect(source,name){
 assert(!/openmates-cli\/src\/sdk(?:Session|-entry|-session-v1-entry)?\.ts/.test(source));
 assert(!source.includes("source('sdkSession')"));
 if(name!=='npm.mjs'){assert(!source.includes('register('));assert(!source.includes('tests/loader.mjs'));}
 const imports=[...source.matchAll(/const\s*\{([^}]+)\}\s*=\s*await import\(([^;\n]+)\);/g)].filter(match=>match[2].includes('/dist/sdk'));
 assert(imports.length>0,'compiled public SDK import required');
 for(const match of imports){
  const entry=vm.runInNewContext(match[2].replaceAll('import.meta.url','runnerUrl'),{URL,runnerUrl:pathToFileURL(path.join(__dirname,name)).href,root,resolve:path.resolve,pathToFileURL});
  const resolvedEntry=new URL(entry,pathToFileURL(path.join(__dirname,name)));
  const filename=path.basename(resolvedEntry.pathname),exportName=filename==='sdk-entry.js'?'./sdk':'./sdk/v1';
  assert(publicExports.has(filename));assert.equal(resolvedEntry.href,pathToFileURL(path.resolve(packageRoot,manifest.exports[exportName].default)).href);
  for(const binding of match[1].split(',').map(s=>s.trim()))assert(publicExports.get(filename).has(binding),'existing public runtime export required: '+binding);
 }
}
for(const name of RUNNERS)test(name+' selects only existing compiled public SDK interfaces',()=>inspect(fs.readFileSync(path.join(__dirname,name),'utf8'),name));
test('boundary rejects restored source-loader entry and unavailable public interface',()=>{
 assert.throws(()=>inspect("const {SessionClient}=await import('../../../frontend/packages/openmates-cli/src/sdkSession.ts');",'session-work.mjs'));
 assert.throws(()=>inspect("const {PrivateUnavailable}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');",'session-work.mjs'));
 assert.throws(()=>inspect("register('private-loader');const {SessionClient}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');",'session-work.mjs'));
});
test('generic adapter retains independent private helper branches and generated public entry',()=>{
 const source=fs.readFileSync(path.join(__dirname,'npm.mjs'),'utf8');
 for(const helper of ['sdkCrypto','crypto','objectSlugs'])assert(source.includes("await import(source('"+helper+"'))"));
 assert(source.includes('register('));assert(source.includes("const { OpenMates } = await import(new URL('../../../frontend/packages/openmates-cli/dist/sdk-entry.js', import.meta.url));"));
});
