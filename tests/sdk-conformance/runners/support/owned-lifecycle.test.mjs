import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {deadline,cleanupOwned,terminateChild,runOwned} from './owned-lifecycle.mjs';
const child=()=>spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});setInterval(()=>{},1000);console.log('ready')"],{stdio:['ignore','pipe','ignore']});
const ready=process=>new Promise(resolve=>process.stdout.once('data',resolve));
test('deadline invokes owner cancellation and clears its timer',async()=>{let cancelled=0;await assert.rejects(deadline(()=>new Promise(()=>{}),10,()=>cancelled++),/owned operation deadline/);assert.equal(cancelled,1);assert.equal(await deadline(()=>42,1000),42);});
test('real child escalates SIGTERM to SIGKILL',async()=>{const process=child();await ready(process);await terminateChild(process,20);assert.equal(process.signalCode,'SIGKILL');});
test('stalled close cannot prevent independent child termination',async()=>{const process=child();await ready(process);await assert.rejects(cleanupOwned({child:process,close:()=>new Promise(()=>{}),graceMs:20}),/owned operation deadline/);assert.equal(process.signalCode,'SIGKILL');});

test('owned timeout awaits child-dependent work settlement and finally cleanup',async()=>{const process=child();await ready(process);const events=[];const exited=new Promise(resolve=>process.once('exit',resolve));await assert.rejects(runOwned(async()=>{try{await exited;events.push('settled');}finally{events.push('work-finally');}},10,()=>{events.push('cancel');process.kill('SIGKILL');},async()=>{await terminateChild(process);events.push('cleanup');}),/owned operation deadline/);assert.deepEqual(events,['cancel','settled','work-finally','cleanup']);assert.equal(process.signalCode,'SIGKILL');});


test('per-read cancellation preserves store owner; watchdog rejects late writes and alias negative control fails',async()=>{
 const {createOwnership}=await import('./owned-lifecycle.mjs');
 const exerciseReadCancel=lease=>{
  let writes=0;const write=()=>{lease.check();writes++;};
  lease.read.abort();assert.equal(lease.read.signal.aborted,true);
  assert.equal(lease.vector.signal.aborted,false,'A cancellation must preserve vector/B ownership');
  write();assert.equal(writes,1,'B persistence remains admitted after A cancellation');
  lease.cancelAll();assert.equal(lease.vector.signal.aborted,true);assert.equal(lease.read.signal.aborted,true);
  assert.throws(write,/owned operation cancelled/);assert.equal(writes,1,'watchdog cannot permit any late write');
 };
 exerciseReadCancel(createOwnership());
 const shared=new AbortController();
 const aliased={vector:shared,read:shared,check(){if(shared.signal.aborted)throw new Error('owned operation cancelled');},cancelAll(){shared.abort();}};
 assert.throws(()=>exerciseReadCancel(aliased),/A cancellation must preserve vector/,'negative control must detect original aliased-controller bug');
});
