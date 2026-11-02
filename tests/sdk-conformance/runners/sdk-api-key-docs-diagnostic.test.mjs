// contract-test-file: tooling
/** Pure extraction: never register loader/import SDK/run docs adapter or transport. */
import test from 'node:test';import assert from 'node:assert/strict';import {readFileSync}from'node:fs';import vm from'node:vm';
const source=readFileSync(new URL('./sdk-api-key-docs.mjs',import.meta.url),'utf8');const a=source.indexOf('// BEGIN CLOSED NPM DOCS DIAGNOSTIC\n'),b=source.indexOf('// END CLOSED NPM DOCS DIAGNOSTIC');assert.ok(a>=0&&b>a);const pure=vm.runInNewContext(source.slice(a+'// BEGIN CLOSED NPM DOCS DIAGNOSTIC\n'.length,b)+'\n({docsError,docsLine,stages:DOCS_CHILD_STAGES,errors:DOCS_CHILD_ERRORS})',{}, {timeout:200});
test('finite npm docs classifier never exports exception values or invokes getters',()=>{
 for(const [error,expected]of [[new TypeError('PRIVATE'),'type'],[new ReferenceError('PRIVATE'),'reference'],[Object.assign(Error('PRIVATE'),{code:'ERR_MODULE_NOT_FOUND'}),'module_not_found'],[Object.assign(Error('PRIVATE'),{name:'OpenMatesApiError'}),'sdk_api']]){assert.equal(pure.docsError(error),expected);assert.ok(!pure.docsLine('invoke',pure.docsError(error)).includes('PRIVATE'));}
 let n=0;const hostile={};for(const key of ['code','name','message','stack'])Object.defineProperty(hostile,key,{get(){n++;throw Error('PRIVATE');}});assert.equal(pure.docsError(hostile),'unclassified');assert.equal(n,0);assert.equal(pure.docsError(new Proxy({},{getOwnPropertyDescriptor(){throw Error('PRIVATE');}})),'unclassified');
});
test('npm docs finite stage formatting closes unknown metadata without invented SDK import attribution',()=>{
 assert.equal(pure.docsLine('PRIVATE','PRIVATE'),'npm docs diagnostic: stage=unclassified;error=unclassified\n');for(const stage of pure.stages)for(const error of pure.errors){const line=pure.docsLine(stage,error);assert.ok(line.length<=150);assert.match(line,/^npm docs diagnostic: stage=[a-z_]+;error=[a-z_]+\n$/);}
});
test('diagnostic wrapper preserves public compiled library entry and no-case driver delegation',()=>{
 assert.ok(source.includes("await import(new URL('../../../frontend/packages/openmates-cli/dist/sdk-entry.js',import.meta.url))"));assert.ok(source.includes("sdk-api-key-docs.py','--language','npm'"));assert.ok(source.includes("catch(e){stage='error_mapping';if(e instanceof OpenMatesConfigError)"));assert.ok(source.includes("assert.ok(e instanceof OpenMatesApiError)"));assert.ok(!source.includes('console.error(error'));assert.ok(!source.includes('error.stack')); // sensitive-logging: allow - conformance runner result protocol on stdout; synthetic fixture data only
});

test('docs import resolves existing compiled public SDK export with no source-loader fallback',()=>{
 const target=/await import\((new URL\([^\n]+\))\)/.exec(source);assert.ok(target);
 const packageRoot=new URL('../../../frontend/packages/openmates-cli/',import.meta.url);
 const manifest=JSON.parse(readFileSync(new URL('package.json',packageRoot),'utf8'));
 const actual=vm.runInNewContext(target[1].replace('import.meta.url','runnerUrl'),{URL,runnerUrl:import.meta.url});
 assert.equal(actual.href,new URL(manifest.exports['./sdk'].default,packageRoot).href);
 assert.equal(actual.href,new URL('dist/sdk-entry.js',packageRoot).href);
 assert.ok(manifest.scripts['build:sdk'].includes('src/sdk-entry.ts'));
 const entry=readFileSync(new URL('src/sdk-entry.ts',packageRoot),'utf8');assert.ok(entry.includes('export * from "./sdk.js"'));
 assert.equal(source.includes('register('),false);assert.equal(source.includes('tests/loader.mjs'),false);assert.equal(source.includes('/src/sdk.ts'),false);
 const driver=readFileSync(new URL('./sdk-api-key-docs.py',import.meta.url),'utf8');
 assert.equal(driver.includes('--experimental-strip-types'),false);assert.equal(driver.includes('--experimental-transform-types'),false);
 assert.ok(driver.includes("return ['node',str(ROOT/'tests/sdk-conformance/runners/sdk-api-key-docs.mjs'),'--case']"));
});
