/** Pure packaging/source-loader checks. No product API or native implementation executes. */
// contract-test-file: tooling
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
const require=createRequire(import.meta.url);
const ts=require('typescript');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
const entry='sdk-session-v1-entry.ts';
const modules=new Set([entry,'sdkSession.ts','sdkEssential.ts','sdkFirstPage.ts','sdkProjectTaskWatch.ts','sdkProjectSources.ts','sdkApiKeyRust.ts','sdkStartupSync.ts','sdkRemoteCrypto.ts','sdkMetadataEphemeral.ts']);
const values=['EphemeralMetadataClient','EphemeralMetadataSnapshot','EphemeralMetadataStartup','MetadataAuthentication','MetadataEphemeralError','RemoteCryptoError','RemoteHandshake','RemoteSession','RustApiKeyClient','RustApiKeyClientError','SessionAccount','SessionChatMonitor','SessionClient','SessionClientError','SessionCompletionRecovery','SessionDrafts','SessionEmbeds','SessionInitialSyncMetadata','SessionInitialSyncOperation','SessionPlans','SessionProjectTaskWatch','SessionProjects','SessionSettingsReadError','SessionTasks','SessionWorkflows'].sort();
const nodeModuleUsers=new Set(['sdkSession.ts','sdkApiKeyRust.ts','sdkRemoteCrypto.ts','sdkMetadataEphemeral.ts']);
const nativeFiles=['darwin-arm64','darwin-x64','linux-arm64','linux-x64','win32-arm64','win32-x64'].map(name=>`../native/${name}.node`);
const source=name=>fs.readFileSync(path.join(root,'src',name),'utf8');
const parse=(name,text=source(name))=>ts.createSourceFile(name,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
function graph(read=source){
 const visited=new Set();
 function visit(name){
  assert(modules.has(name),`Non-SDK module in versioned graph: ${name}`);
  if(visited.has(name))return;visited.add(name);
  const tree=parse(name,read(name));
  function walk(node){
   if((ts.isImportDeclaration(node)||ts.isExportDeclaration(node))&&node.moduleSpecifier){
    assert(ts.isStringLiteral(node.moduleSpecifier),'Nonliteral module edge');const spec=node.moduleSpecifier.text;
    if(spec==='node:module')assert.equal(nodeModuleUsers.has(name),true);
    else {assert(/^\.\/[A-Za-z0-9]+\.js$/.test(spec),`Forbidden SDK import: ${spec}`);visit(spec.slice(2,-3)+'.ts');}
   }
   if(ts.isCallExpression(node)){
    if(node.expression.kind===ts.SyntaxKind.ImportKeyword)assert.fail('Dynamic module import in supported graph');
    if(ts.isIdentifier(node.expression)&&node.expression.text==='require'){
     assert.equal(name==='sdkSession.ts'||name==='sdkApiKeyRust.ts',true);
     assert.equal(node.arguments.length,1);assert(ts.isStringLiteral(node.arguments[0]));assert(nativeFiles.includes(node.arguments[0].text),'Only fixed packaged native artifact requests are permitted');
    }
    if(ts.isIdentifier(node.expression))assert(!['eval','Function'].includes(node.expression.text));
   }
   ts.forEachChild(node,walk);
  }
  walk(tree);
 }
 visit(entry);return visited;
}
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless
 test('versioned export and both build paths are additive; root, wildcard and CLI stay intact',()=>{
 assert.deepEqual(manifest.exports['./sdk/v1'],{types:'./dist/sdk-session-v1-entry.d.ts',default:'./dist/sdk-session-v1-entry.js'});
 assert.deepEqual(manifest.exports['.'],{types:'./dist/index.d.ts',default:'./dist/index.js'});
 assert.deepEqual(manifest.exports['./sdk'],{types:'./dist/sdk-entry.d.ts',default:'./dist/sdk-entry.js'});
 assert.equal(manifest.exports['./*'],'./*');assert.equal(manifest.main,'dist/index.js');assert.equal(manifest.types,'dist/index.d.ts');assert.equal(manifest.bin.openmates,'dist/cli.js');
 for(const file of ['src/index.ts','src/sdk-entry.ts','src/sdk-session-v1-entry.ts','src/cli.ts','src/remoteAccessCrypto.ts','src/privacyDaemon.ts'])assert(manifest.scripts.build.split(' ').includes(file));
 for(const file of ['src/sdk-entry.ts','src/sdk-session-v1-entry.ts'])assert(manifest.scripts['build:sdk'].split(' ').includes(file));
 for(const shipped of ['dist','native/*.node','fixtures','templates'])assert(manifest.files.includes(shipped));
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless
 test('finite named public export inventory resolves to actual direct-client declarations',()=>{
 const tree=parse(entry);const names=new Set(),runtime=[];
 for(const statement of tree.statements){
  assert(ts.isExportDeclaration(statement),'Versioned barrel contains executable implementation');
  assert(statement.exportClause&&ts.isNamedExports(statement.exportClause),'No blanket export is permitted');
  const target=statement.moduleSpecifier.text.slice(2,-3)+'.ts';assert(modules.has(target));const declarations=parse(target).statements;
  for(const item of statement.exportClause.elements){
   assert(!item.propertyName,'No renamed credential constructors');assert(!names.has(item.name.text));names.add(item.name.text);assert(!item.name.text.startsWith('Native'));
   const declaration=declarations.find(candidate=>candidate.name?.text===item.name.text&&candidate.modifiers?.some(m=>m.kind===ts.SyntaxKind.ExportKeyword));assert(declaration,`Missing actual public declaration ${item.name.text}`);
   if(!statement.isTypeOnly) {assert(ts.isClassDeclaration(declaration));runtime.push(item.name.text);}
  }
 }
 assert.deepEqual(runtime.sort(),values);assert.equal(names.size,104);
 for(const forbidden of ['OpenMates','OpenMatesClient','APP_SKILL_METADATA','sortTasks','NativeEssential'])assert(!names.has(forbidden));
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
 test('actual complete type/runtime graph excludes CLI, storage and TS-only policy; injected regressions fail',()=>{
 assert.deepEqual([...graph()].sort(),[...modules].sort());
 assert.throws(()=>graph(name=>name===entry?'export { OpenMatesClient } from "./client.js";':source(name)),/Non-SDK module/);
 assert.throws(()=>graph(name=>name===entry?'export { execFile } from "node:child_process";':source(name)),/Forbidden SDK import/);
 assert.throws(()=>graph(name=>name===entry?'export * from "./sdk.js";':source(name)),/Non-SDK module/);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless
 test('actual finite public types compile and declaration emission keeps supported relative edges',()=>{
 const outputs=new Map();
 const program=ts.createProgram([path.join(root,'src',entry)],{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.NodeNext,moduleResolution:ts.ModuleResolutionKind.NodeNext,strict:true,skipLibCheck:true,types:['node'],declaration:true,emitDeclarationOnly:true,outDir:path.join(root,'.sdk-v1-type-probe')});
 const diagnostics=ts.getPreEmitDiagnostics(program);assert.equal(diagnostics.length,0,ts.formatDiagnosticsWithColorAndContext(diagnostics,{getCurrentDirectory:()=>root,getCanonicalFileName:name=>name,getNewLine:()=>"\n"}));
 const emitted=program.emit(undefined,(file,text)=>outputs.set(path.basename(file),text));assert.equal(emitted.emitSkipped,false);
 const declaration=outputs.get('sdk-session-v1-entry.d.ts');assert(declaration);
 const tree=ts.createSourceFile('sdk-session-v1-entry.d.ts',declaration,ts.ScriptTarget.Latest,true);
 for(const statement of tree.statements){assert(ts.isExportDeclaration(statement));assert(statement.exportClause&&ts.isNamedExports(statement.exportClause));const target=statement.moduleSpecifier.text.slice(2,-3)+'.d.ts';assert(outputs.has(target),`Missing emitted declaration ${target}`);}
});
function isolatedImport(incompatible){
 const fixture=fs.mkdtempSync(path.join(os.tmpdir(),'openmates-sdk-v1-package-'));const home=path.join(fixture,'isolated-home');fs.mkdirSync(home);fs.mkdirSync(path.join(home,'.openmates'));fs.writeFileSync(path.join(home,'.openmates','session.json'),'SYNTHETIC-CLI-SESSION-DO-NOT-READ');
 try{
  fs.writeFileSync(path.join(fixture,'package.json'),JSON.stringify(manifest));fs.mkdirSync(path.join(fixture,'dist'));
  // Emit exact current source with TS erasure only. This is not a tsup/native build.
  for(const name of graph()){
   const output=ts.transpileModule(source(name),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022},fileName:name,reportDiagnostics:true});
   assert(!output.diagnostics?.some(d=>d.category===ts.DiagnosticCategory.Error));fs.writeFileSync(path.join(fixture,'dist',name.replace(/\.ts$/,'.js')),output.outputText);
  }
  // Keep legacy physical entry sentinel: only the new package subpath is loaded.
  fs.writeFileSync(path.join(fixture,'dist/index.js'),'throw new Error("legacy root loaded");');
  if(incompatible){fs.mkdirSync(path.join(fixture,'native'));for(const file of nativeFiles)fs.writeFileSync(path.join(fixture,'dist',file),'invalid-native-artifact');}
  const runner=String.raw`
import assert from 'node:assert/strict';
import fs from 'node:fs';
import child from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {fileURLToPath} from 'node:url';
const forbiddenHome=process.env.HOME;
let reads=0,spawns=0;
for(const method of ['readFileSync','readFile','writeFileSync','writeFile','openSync','open','readdirSync','statSync','accessSync','existsSync']){
 const original=fs[method];fs[method]=function(file,...args){const value=file instanceof URL?fileURLToPath(file):String(file);if(value.startsWith(forbiddenHome)){reads++;throw Error('CLI state access prohibited');}return original.call(this,file,...args);};
}
for(const method of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork'])child[method]=()=>{spawns++;throw Error('Child process prohibited');};
syncBuiltinESMExports();
assert(import.meta.resolve('openmates/sdk/v1').endsWith('/dist/sdk-session-v1-entry.js'));
assert(import.meta.resolve('openmates').endsWith('/dist/index.js'));
assert(import.meta.resolve('openmates/sdk').endsWith('/dist/sdk-entry.js'));
const sdk=await import('openmates/sdk/v1');
assert.deepEqual(Object.keys(sdk).sort(),EXPECTED);
assert.throws(()=>new sdk.SessionClient(),e=>e instanceof sdk.SessionClientError&&e.code==='invalid_argument');
assert.throws(()=>new sdk.RustApiKeyClient(),e=>e instanceof sdk.RustApiKeyClientError&&e.code==='invalid_argument');
assert.throws(()=>new sdk.SessionClient({apiUrl:'https://api.example.invalid',privacy:{enhanced:false},allowPrivateOperations:false}),e=>e instanceof sdk.SessionClientError&&e.code==='native_binding_unavailable');
assert.throws(()=>new sdk.RustApiKeyClient({apiKey:'synthetic-explicit-key',apiUrl:'https://api.example.invalid',deviceId:'synthetic-device',privacy:{enhanced:false},allowPrivateOperations:false}),e=>e instanceof sdk.RustApiKeyClientError&&e.code==='native_binding_unavailable');
assert.equal(reads,0);assert.equal(spawns,0);
console.log('versioned import/explicit constructors/native refusal: passed');
`.replace('EXPECTED',JSON.stringify(values));
  fs.writeFileSync(path.join(fixture,'probe.mjs'),runner);
  const result=spawnSync(process.execPath,[path.join(fixture,'probe.mjs')],{cwd:fixture,encoding:'utf8',timeout:15000,env:{PATH:'/nonexistent',HOME:home,USERPROFILE:home,OPENMATES_API_KEY:'synthetic-ambient-key-must-not-be-used',OPENMATES_API_URL:'https://ambient.example.invalid',OPENMATES_SESSION_PATH:path.join(home,'.openmates/session.json')}});
  assert.equal(result.status,0,result.stdout+'\n'+result.stderr);assert.match(result.stdout,/passed/);
 }finally{fs.rmSync(fixture,{recursive:true,force:true});}
}
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
 test('actual package self-reference imports without CLI state and refuses missing native binding',()=>isolatedImport(false));
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
 test('incompatible native artifacts produce typed refusal without CLI fallback or ambient credentials',()=>isolatedImport(true));
