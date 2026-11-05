// contract-test-file: tooling
// Actual web Format C/D functions, synthetic key resources only; no API/account.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createRequire}=require('node:module'),{webcrypto}=require('node:crypto');
const root=path.resolve(__dirname,'../..');
async function verify(batch){
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'tests/sdk-conformance/fixtures/work-server-field-interop.json'),'utf8'));
 if(fixture.version!==1||fixture.wire.iv_bytes!==12||fixture.wire.tag_bytes!==16||fixture.wire.prefix_bytes!==0)throw Error('fixture_contract');
 if(!batch||batch.version!==1||!Array.isArray(batch.cases)||batch.cases.length<1||batch.cases.length>128)throw Error('input');
 const load=createRequire(path.join(root,'frontend/apps/web_app/package.json')),ts=load('typescript');
 const source=fs.readFileSync(path.join(root,'frontend/packages/ui/src/services/encryption/MetadataEncryptor.ts'),'utf8');
 const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},reportDiagnostics:true});if(compiled.diagnostics.length)throw Error('syntax');
 let activeMaster=null,exportsAttempted=0;
 Object.defineProperty(webcrypto.subtle,'exportKey',{configurable:true,value(){exportsAttempted++;throw Error('export_forbidden');}});
 const platform={uint8ArrayToBase64:bytes=>Buffer.from(bytes).toString('base64'),base64ToUint8Array:value=>new Uint8Array(Buffer.from(value,'base64')),getKeyFromStorage:async()=>activeMaster};
 const module={exports:{}};
 vm.runInNewContext('(function(exports,require,module){'+compiled.outputText+'})',{crypto:webcrypto,CryptoKey:globalThis.CryptoKey,Uint8Array,ArrayBuffer,TextEncoder,TextDecoder,console:{error(){},warn(){},debug(){},log(){}}})(module.exports,name=>{if(name!=='../cryptoService')throw Error('dependency');return platform;},module);
 const web=module.exports;
 const open=async(row,cipher,key,master,aad)=>{
  activeMaster=master;
  if(row.kind==='master-binary')return web.decryptChatKeyWithMasterKey(cipher,master);
  if(row.kind==='master-text')return web.decryptWithMasterKeyDirect(cipher,master);
  if(row.kind==='object-binary')return web.unwrapEmbedKeyWithChatKey(cipher,key);
  if(row.kind==='object-text')return web.decryptWithEmbedKey(cipher,key,aad?{associatedData:aad}:{});
  throw Error('kind');
 };
 for(const row of batch.cases){
  if(Object.keys(row).sort().join('|')!=='aad|ciphertext|expected_b64|key_b64|kind|label')throw Error('shape');
  if(typeof row.ciphertext!=='string'||row.ciphertext.length>2*1024*1024||typeof row.expected_b64!=='string'||row.expected_b64.length>2*1024*1024||typeof row.aad!=='string'||row.aad.length>1024)throw Error('bounds');
  if(!fixture.decoderKinds.includes(row.kind))throw Error('decoder_kind');
  const key=new Uint8Array(Buffer.from(row.key_b64,'base64')),expected=Buffer.from(row.expected_b64,'base64'),wire=Buffer.from(row.ciphertext,'base64');
  if(key.length!==32||wire.length!==expected.length+28)throw Error('legacy_layout');
  const master=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt','decrypt']);if(master.extractable)throw Error('resource');
  const result=await open(row,row.ciphertext,key,master,row.aad);
  if(result===null||!Buffer.from(typeof result==='string'?new TextEncoder().encode(result):result).equals(expected))throw Error('plaintext');
  const tampered=Buffer.from(wire);tampered[tampered.length-1]^=1;
  if(await open(row,tampered.toString('base64'),key,master,row.aad)!==null)throw Error('tamper');
  const wrong=key.slice();wrong[0]^=1;const wrongMaster=await webcrypto.subtle.importKey('raw',wrong,'AES-GCM',false,['decrypt']);
  if(await open(row,row.ciphertext,wrong,wrongMaster,row.aad)!==null)throw Error('wrongkey');
  if(row.aad&&await open(row,row.ciphertext,key,master,'wrong-context:'+row.aad)!==null)throw Error('aad');
  key.fill(0);wrong.fill(0);activeMaster=null;
 }
 if(exportsAttempted!==0)throw Error('export');
 return {status:'passed',cases:batch.cases.length,exportsAttempted};
}
module.exports={verify};
if(require.main===module){(async()=>{const raw=fs.readFileSync(0);if(raw.length>4*1024*1024)throw Error('bounds');const result=await verify(JSON.parse(raw));process.stdout.write(JSON.stringify(result));})().catch(()=>{process.stderr.write('work_field_web_decode_failed');process.exitCode=1;});}
