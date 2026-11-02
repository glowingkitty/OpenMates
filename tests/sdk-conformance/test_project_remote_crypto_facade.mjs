/** Pure actual facade extraction with inert native double: no SDK/native/crypto execution. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const root=fileURLToPath(new URL('../../',import.meta.url));
const ts=createRequire(root+'/frontend/packages/openmates-cli/package.json')('typescript');
let calls=[];
const nativeSession={seal:(id,value)=>{calls.push(['seal',id,value]);return '{"version":1,"nonce":"public","ciphertext":"public"}';},open:()=>new Uint8Array([0,255]),openJsonText:()=>'{"n":9007199254740993}',close:()=>calls.push(['close-session'])};
const instances=[];
function closed(){return new Error(JSON.stringify({code:'crypto',message:'Encrypted data could not be authenticated.'}));}
class Native {
 constructor(key,identity,role){this.closed=false;this.closeCount=0;this.finishCount=0;this.closeThrows=false;instances.push(this);calls.push(['new',key,identity,role]);}
 handshakeJson(){if(this.closed)throw closed();return '{"version":1,"role":"requester","publicKey":"public","authenticationTag":"public"}';}
 finish(value){this.finishCount++;if(this.closed)throw closed();this.closed=true;calls.push(['finish',value]);return nativeSession;}
 close(){this.closed=true;this.closeCount++;calls.push(['close-handshake']);if(this.closeThrows)throw new Error('synthetic cleanup refusal');}
}
const source=readFileSync(root+'/frontend/packages/openmates-cli/src/sdkRemoteCrypto.ts','utf8');
const tree=ts.createSourceFile('facade.ts',source,ts.ScriptTarget.Latest,true);
const text=tree.statements.filter(node=>!ts.isImportDeclaration(node)).map(node=>node.getText(tree)).join('\n').replaceAll('import.meta.url','"inert-url"');
const code=ts.transpileModule(text,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{},Error,Uint8Array,JSON,Number,process:{platform:'linux',arch:'arm64'},createRequire:()=>()=>({NativeRemoteHandshake:Native})};vm.runInNewContext(code,context);
const {RemoteHandshake,RemoteCryptoError}=context.exports;
const key=new Uint8Array(32),identity={ownerId:'synthetic',projectId:'p',sourceId:'s',sourceSessionId:'a',requestingClientId:'b',keyEpoch:1};
const pending=new RemoteHandshake(key,identity,'requester');assert.equal(calls[0][1],key);assert.deepEqual(JSON.parse(calls[0][2]),identity);assert.ok(!calls[0][2].includes('privateKey'));
const wire=pending.handshake(),session=pending.finish(wire);
assert.equal(session.openJsonText('id',{}),'{"n":9007199254740993}','no implicit Number parse after Core consumes nonce');
assert.deepEqual(session.open('id',{}),new Uint8Array([0,255]));
session.seal('id',new Uint8Array([0,255]));session.close();pending.close();
assert.ok(calls.some(row=>row[0]==='close-session'));assert.ok(calls.some(row=>row[0]==='close-handshake'));
new RemoteHandshake(key,{...identity,keyEpoch:9007199254740992},'requester');assert.ok(JSON.parse(calls.at(-1)[2]).keyEpoch>9007199254740991,'Core alone enforces the existing safe epoch limit');
assert.throws(()=>new RemoteHandshake('secret-string',identity,'requester'),error=>error instanceof RemoteCryptoError&&error.code==='invalid_argument');
nativeSession.open=()=>{throw new Error(JSON.stringify({code:'crypto',message:'Encrypted data could not be authenticated.'}));};
assert.throws(()=>session.open('id',{}),error=>error instanceof RemoteCryptoError&&error.code==='crypto'&&!error.message.includes('private'));
const cyclic={};cyclic.self=cyclic;
for(const remote of [cyclic,{big:1n},undefined,Symbol('wire'),()=>{}]){
 const a=new RemoteHandshake(key,identity,'requester'),original=instances.at(-1);
 const sibling=new RemoteHandshake(key,identity,'source'),other=instances.at(-1);
 assert.throws(()=>a.finish(remote),error=>error instanceof RemoteCryptoError&&error.code==='native_failure');
 assert.equal(original.closeCount,1);assert.equal(original.finishCount,0);assert.equal(other.closeCount,0);
 assert.throws(()=>a.handshake(),error=>error instanceof RemoteCryptoError&&error.code==='crypto');
 assert.throws(()=>a.finish(wire),error=>error instanceof RemoteCryptoError&&error.code==='crypto');
 assert.equal(sibling.handshake().publicKey,'public');sibling.close();
}
{
 const a=new RemoteHandshake(key,identity,'requester'),original=instances.at(-1);original.closeThrows=true;
 const preserved=new RemoteCryptoError('synthetic_original','Synthetic original refusal.');
 const remote={toJSON(){throw preserved;}};
 assert.throws(()=>a.finish(remote),error=>error===preserved,'cleanup never replaces the original typed serializer error');
 assert.equal(original.closed,true);assert.equal(original.closeCount,1);assert.equal(original.finishCount,0);
}
console.log(JSON.stringify({kind:'pure actual remote facade with inert native double',checks:15,nativeSDKExecuted:false,network:false}));
