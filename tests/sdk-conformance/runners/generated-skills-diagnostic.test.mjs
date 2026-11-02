// Pure actual projection/catch-unit fixtures only. No SDK adapter, REST or CI.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {extractGeneratedDiagnostic,generatedDigestCatalog,decodeGeneratedDigest,digest} from './generated-skills-diagnostic.mjs';
const source=readFileSync(new URL('./npm.mjs',import.meta.url),'utf8');
const helper=extractGeneratedDiagnostic(source);
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('actual formatter permits only finite stage vector error labels',()=>{
  const marker='synthetic-private-body-secret';
  const line=helper.line(marker,marker,marker);
  assert.equal(line,'npm generated-skills diagnostic: stage=unclassified;vector=none;error=unclassified\n');
  assert.equal(line.includes(marker),false);
  assert.equal(helper.generic,'npm SDK conformance failed: protocol.generated-skills.v1\n');
  for(const stage of helper.suiteOnly)assert.ok(helper.line(stage,'generated-web-search','module_not_found').includes(';vector=none;'));
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('closed error categories inspect no message stack body or getter',()=>{
  const data={code:'ERR_MODULE_NOT_FOUND'};
  for(const key of ['message','stack','body','path','url'])Object.defineProperty(data,key,{get(){throw Error('must not inspect private field');}});
  assert.equal(helper.classify(data),'module_not_found');
  const getter={};Object.defineProperty(getter,'code',{get(){throw Error('must not execute code getter');}});
  assert.equal(helper.classify(getter),'unclassified');
  assert.equal(helper.classify(new Proxy({},{getPrototypeOf(){throw Error('private');}})),'unclassified');
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('actual classifier retains distinct bounded error categories',()=>{
  for(const [error,kind]of [[{code:'ERR_ASSERTION'},'assertion'],[{code:'ERR_PACKAGE_PATH_NOT_EXPORTED'},'module_export_missing'],[{code:'ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX'},'unsupported_ts_syntax'],[new SyntaxError('private'),'syntax'],[new TypeError('private'),'type'],[new ReferenceError('private'),'reference'],[{name:'OpenMatesConfigError'},'sdk_config'],[{name:'OpenMatesApiError'},'sdk_api'],[undefined,'unclassified']])assert.equal(helper.classify(error),kind);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('every finite actual stderr variant decodes by exact retained bytes and SHA only',()=>{
  const {entries}=generatedDigestCatalog(source);
  assert.equal(entries.size,(helper.stages.length*helper.vectors.length-helper.suiteOnly.length)*helper.errors.length);
  for(const [key,expected]of entries){const [bytes,sha]=key.split(':');const result=decodeGeneratedDigest(source,Number(bytes),sha);assert.deepEqual(result,{status:'matched',...expected,attribution:expected.vector==='none'?'suite-only':'admitted-vector'});}
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('unknown or changed digest never guesses case or boundary and old generic is suite-only',()=>{
  assert.deepEqual(decodeGeneratedDigest(source,57,'0'.repeat(64)),{status:'unmatched'});
  assert.deepEqual(decodeGeneratedDigest(source,Buffer.byteLength(helper.generic),digest(helper.generic)),{status:'generic-only',stage:'unclassified',vector:'none',error:'unclassified',attribution:'suite-only'});
  assert.throws(()=>decodeGeneratedDigest(source,-1,'0'.repeat(64)));
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('actual catch keeps generic first and exit1 with generated-only finite suffix',()=>{
  const start=source.lastIndexOf('} catch (error) {');assert.ok(start>=0);
  const body=source.slice(start+'} catch (error) {'.length,-2);
  for(const capability of ['protocol.generated-skills.v1','crypto.slug-lookup.v1']){
    const writes=[],process={stderr:{write:text=>writes.push(text)},exitCode:0};
    vm.runInNewContext(body,{process,capability,error:{code:'ERR_MODULE_NOT_FOUND'},generatedDiagnosticStage:'sdk_import',generatedDiagnosticVector:'none',generatedDiagnosticLine:helper.line,generatedDiagnosticError:helper.classify});
    assert.equal(process.exitCode,1);assert.equal(writes[0],`npm SDK conformance failed: ${capability}\n`);
    assert.equal(writes.length,capability==='protocol.generated-skills.v1'?2:1);
    if(writes.length===2)assert.deepEqual(decodeGeneratedDigest(source,Buffer.byteLength(writes.join('')),digest(writes.join(''))),{status:'matched',stage:'sdk_import',vector:'none',error:'module_not_found',attribution:'suite-only'});
  }
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('vector remains none before real admission and library import precedes admission',()=>{
  assert.ok(source.indexOf("generatedDiagnosticStage='sdk_import'")<source.indexOf("generatedDiagnosticVector=vector&&"));
  assert.equal((source.match(/generatedDiagnosticVector=vector&&/g)||[]).length,1);
  assert.ok(source.includes("results.push({ id: vector.id, status: 'passed' });\n      generatedDiagnosticVector='none';"));
  assert.ok(source.includes("vector.id==='generated-web-search'?'generated-web-search':'none'"));
  for(const stage of ['client_constructor','generated_dispatch','response_assert','call_count_assert','method_assert','path_assert','body_assert','authorization_assert'])assert.ok(source.includes(`generatedDiagnosticStage='${stage}'`));
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('actual finally restores original failure stage unless restoring fetch itself fails',()=>{
  const match=/\} finally \{\n(\s+const generatedBeforeRestore=generatedDiagnosticStage;[\s\S]*?)\n      \}/.exec(source);assert.ok(match);
  const state={generatedDiagnosticStage:'body_assert',globalThis:{fetch:'temporary'},previous:'original'};
  vm.runInNewContext(match[1],state);assert.equal(state.generatedDiagnosticStage,'body_assert');assert.equal(state.globalThis.fetch,'original');
  const broken={generatedDiagnosticStage:'body_assert',globalThis:{},previous:'original'};Object.defineProperty(broken.globalThis,'fetch',{set(){throw Error('private');}});
  assert.throws(()=>vm.runInNewContext(match[1],broken));assert.equal(broken.generatedDiagnosticStage,'fetch_restore');
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('removing diagnostic-only nodes restores every original fa3 program token',()=>{
  const baselineTokenSha='5ac576dc5224660c4f048b18d8ef2156984b957e020a092b9d5d75f3f3ad1ce7';
  const stripped=source
    .replace("await import(new URL('../../../frontend/packages/openmates-cli/dist/sdk-entry.js', import.meta.url))", "await import(source('sdk-entry'))")
    .replace(/\/\/ BEGIN CLOSED GENERATED SKILLS DIAGNOSTIC\n[\s\S]*?\/\/ END CLOSED GENERATED SKILLS DIAGNOSTIC\nlet generatedDiagnosticStage='arguments',generatedDiagnosticVector='none';\n/,'')
    .replace(/\n  if\(capability==='protocol\.generated-skills\.v1'\)\{\n    try\{process\.stderr\.write\(generatedDiagnosticLine\(generatedDiagnosticStage,generatedDiagnosticVector,generatedDiagnosticError\(error\)\)\);\}catch\{\}\n  \}/,'')
    .replace(/^\s*generatedDiagnostic(?:Stage|Vector)=[^\n]*;\n/gm,'')
    .replace(/^\s*const generatedBeforeRestore=generatedDiagnosticStage;\n/gm,'')
    .replace('} catch (error) {\n  process.stderr.write','} catch {\n  process.stderr.write');
  const tokens=stripped.match(/'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\])*`|\/\/[^\n]*|\/\*[\s\S]*?\*\/|[^\s]/g);
  assert.equal(digest(tokens.join('\0')),baselineTokenSha);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
test('offline CLI accepts only exact runner hash and retained digest metadata',async()=>{
  const {spawnSync}=await import('node:child_process');const {fileURLToPath}=await import('node:url');
  const text=helper.generic+helper.line('body_assert','generated-web-search','assertion');
  const args=[fileURLToPath(new URL('./generated-skills-diagnostic.mjs',import.meta.url)),'--runner',fileURLToPath(new URL('./npm.mjs',import.meta.url)),'--runner-sha256',digest(source),'--stderr-bytes',String(Buffer.byteLength(text)),'--stderr-sha256',digest(text)];
  const result=spawnSync(process.execPath,args,{encoding:'utf8',timeout:5000});assert.equal(result.status,0);assert.equal(result.stderr,'');
  assert.deepEqual(JSON.parse(result.stdout),{runnerSha256:digest(source),status:'matched',stage:'body_assert',vector:'generated-web-search',error:'assertion',attribution:'admitted-vector'});
  const bad=[...args];bad[4]='0'.repeat(64);const refused=spawnSync(process.execPath,bad,{encoding:'utf8',timeout:5000});assert.equal(refused.status,1);assert.equal(refused.stdout,'');assert.equal(refused.stderr,'generated_skills_decoder_refused\n');
});

// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation,sdk.surface.semantic-parity
test('generated skills imports the built public SDK entry without source-loader redirection',async()=>{
  const expression=/const \{ OpenMates \} = await import\(([^\n]+)\);/.exec(source);
  assert.ok(expression);
  const packageRoot=new URL('../../../frontend/packages/openmates-cli/',import.meta.url);
  const manifest=JSON.parse(readFileSync(new URL('package.json',packageRoot),'utf8'));
  const entry=vm.runInNewContext(expression[1].replace('import.meta.url','runnerUrl'),{URL,runnerUrl:import.meta.url});
  assert.equal(entry.href,new URL(manifest.exports['./sdk'].default,packageRoot).href);
  assert.equal(entry.href,new URL('dist/sdk-entry.js',packageRoot).href);
  assert.equal(source.includes("await import(source('sdk-entry'))"),false);
  const loader=readFileSync(new URL('tests/loader.mjs',packageRoot),'utf8');
  const resolve=vm.runInNewContext(loader.replace('export async function resolve','async function resolve')+'\nresolve',{URL});
  const observed=[];const next=async(specifier,context)=>{observed.push([specifier,context.parentURL]);return {url:specifier};};
  const context={parentURL:import.meta.url};
  assert.equal((await resolve(entry.href,context,next)).url,entry.href);
  const distContext={parentURL:entry.href};
  assert.equal((await resolve('./chunk.js',distContext,next)).url,'./chunk.js');
  assert.equal(observed.length,2);
  assert.ok(manifest.scripts['build:sdk'].includes('src/sdk-entry.ts'));
  assert.ok(source.includes("new OpenMates({ apiKey: 'sk-api-synthetic-conformance.synthetic-local-setup-secret', apiUrl: 'https://api.example.invalid', deviceId: 'synthetic-conformance' })"));
});
