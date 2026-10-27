// contract-test-file: tooling
// Inert text and owned-process mocks only; no Wasm, browser, network or providers.
import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {parseWorkerOutput,cleanupOwned} from '../ci_wasm_worker.mjs';
const names=Array.from({length:8},(_,i)=>'browser::browser_crypto_tests::case_'+i);
const output=(ids=names)=>ids.map(n=>'test '+n+' ... ok').join('\n')+'\ntest result: ok. '+ids.length+' passed; 0 failed; 0 ignored; 0 filtered out; finished in 0.01s\n';
test('exact actual output grammar requires each named Rust test once and zero skipped/ignored/failures',()=>{
 assert.equal(parseWorkerOutput(output(),names).passed,8);
 for(const raw of [output(names.slice(1)),output([...names,names[0]]),output().replace('case_1 ... ok','case_1 ... FAILED'),output().replace('0 ignored','1 ignored'),output().replace('0 filtered out','1 filtered out'),output()+'test result: ok. 8 passed; 0 failed; 0 ignored; 0 filtered out\n','test result: ok. 0 passed; 0 failed; 0 ignored; 0 filtered out\n','x'.repeat(256*1024+1)])assert.throws(()=>parseWorkerOutput(raw,names),/refused/);
});
test('ninth actual compiled test is required automatically when supplied',()=>{
 const ids=[...names,'browser::browser_crypto_tests::existing_key_handoff'];
 assert.equal(parseWorkerOutput(output(ids),ids).passed,9);
 assert.throws(()=>parseWorkerOutput(output(),ids),/refused/);
});
function child(mode){
 const server=new EventEmitter(),signals=[];let exit;
 server.kill=signal=>{signals.push(signal);if(mode!=='hang'){exit={code:mode==='bad-code'?0:null,signal};queueMicrotask(()=>server.emit('exit',exit.code,exit.signal));}return true;};
 return {server,signals,get:()=>exit};
}
test('manual-server cleanup closes browser and reaps expected owned signal exit',async()=>{
 const c=child('normal');let closed=0;
 assert.equal(await cleanupOwned({close:async()=>{closed++;}},c.server,c.get,20),true);
 assert.equal(closed,1);assert.deepEqual(c.signals,['SIGTERM']);
});
test('browser failure, unexpected server exit or unreaped server cannot claim cleanup success',async()=>{
 const bad=child('bad-code');assert.equal(await cleanupOwned({close:async()=>{}},bad.server,bad.get,5),false);
 const close=child('normal');assert.equal(await cleanupOwned({close:async()=>{throw Error('private');}},close.server,close.get,5),false);assert.deepEqual(close.signals,['SIGTERM']);
 const hang=child('hang');assert.equal(await cleanupOwned({close:async()=>{}},hang.server,hang.get,2),false);assert.deepEqual(hang.signals,['SIGTERM','SIGKILL']);
});
test('public BrowserServer owner must confirm browser child termination, with force cleanup on failure',async()=>{
 const c=child('normal'),proc={exitCode:null,signalCode:null};let forced=0;
 const owner={process:()=>proc,close:async()=>{proc.exitCode=0;},kill:async()=>{forced++;proc.signalCode='SIGKILL';}};
 assert.equal(await cleanupOwned(undefined,c.server,c.get,10,owner),true);assert.equal(forced,0);
 const d=child('normal');proc.exitCode=null;proc.signalCode=null;
 owner.close=async()=>{throw Error('private');};
 assert.equal(await cleanupOwned(undefined,d.server,d.get,10,owner),false);assert.equal(forced,1);assert.equal(proc.signalCode,'SIGKILL');
});
