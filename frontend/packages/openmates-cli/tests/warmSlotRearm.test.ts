import { it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { OpenMatesClient } from '../src/client.ts';
import { PreparedPrivacyCache } from '../src/preparedPrivacy.ts';
const previous=process.env.OPENMATES_STATE_DIR,dir=mkdtempSync(join(tmpdir(),'cli-slot-rearm-'));
before(()=>{process.env.OPENMATES_STATE_DIR=dir;});
after(()=>{if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;rmSync(dir,{recursive:true,force:true});});
const options={taskUpdateJobs:true,projectFileJobs:true,remoteCommandJobs:true,interactiveHuman:true};
function fixture(){
 const client=OpenMatesClient.load() as any;
 client.session={apiUrl:'http://fixture.invalid',hashedEmail:'fixture',sessionId:'fixture',createdAt:1,activeTeamId:null,
  masterKeyExportedB64:Buffer.alloc(32).toString('base64'),wsToken:'token',cookies:{auth_refresh_token:'cookie'}};
 client.interactiveViewerAllowed=true;client.foregroundSendCount=0;client.explicitSession=false;client.preparedPrivacy=new PreparedPrivacyCache();client.preparedPrivacyEpoch=0;
 client.http={getCookieMap:()=>client.session.cookies};client.withFreshStoredSession=async(work:()=>unknown)=>work();
 const opened:any[]=[];
 client.openWsClient=async(flags:any)=>{
  assert.deepEqual(Object.fromEntries(Object.entries(flags).filter(([key])=>key!=='signal')),options);
  let open=true;const listeners=new Set<()=>void>();
  const ws={listenerCount:()=>listeners.size,isOpen:()=>open,onClose:(cb:()=>void)=>{listeners.add(cb);return()=>listeners.delete(cb);},close:()=>{
   if(!open)return;open=false;for(const cb of [...listeners])cb();}};
  const result={ws,session:client.session,ownerId:'owner'};opened.push(result);return result;
 };
 return {client,opened};
}
// contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
it('replenishes distinct unused slots for repeated same-owner turns only after cleanup and close',async()=>{
 const {client,opened}=fixture();
 for(let turn=0;turn<3;turn++){
  client.warmSendSocket();await client.preparedSendSocket?.pending;
  const borrowed=await client.takePreparedSendSocket(options,null);assert.equal(borrowed,opened[turn]);
  client.foregroundSendCount=1;client.rearmSendSocketWhenClosed(borrowed.ws,null);
  client.warmSendSocket();assert.equal(opened.length,turn+1,'render warmup cannot rotate auth during a send');
  borrowed.ws.close();assert.equal(opened.length,turn+1,'close alone cannot bypass foreground cleanup');
  client.foregroundSendCount=0;client.maybeRearmSendSocket();await client.preparedSendSocket?.pending;
  assert.equal(opened.length,turn+2);assert.notEqual(opened[turn+1].ws,borrowed.ws);
  for(let repeat=0;repeat<3;repeat++)client.warmSendSocket();assert.equal(opened.length,turn+2,'one unused slot only');
 }
 client.endInteractiveViewerSession();
});
// contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
it('waits for optional metadata transport release even after foreground cleanup',async()=>{
 const {client,opened}=fixture();client.warmSendSocket();await client.preparedSendSocket.pending;
 const borrowed=await client.takePreparedSendSocket(options,null);client.rearmSendSocketWhenClosed(borrowed.ws,null);
 client.maybeRearmSendSocket();assert.equal(opened.length,1);
 borrowed.ws.close();await client.preparedSendSocket.pending;assert.equal(opened.length,2);client.endInteractiveViewerSession();
});
for(const change of ['account','session','key','team','cookie','http-cookie','token','end','new-send'] as const){
 // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
 it(`does not rearm an obsolete completion after changed ${change}`,async()=>{
  const {client,opened}=fixture();client.warmSendSocket();await client.preparedSendSocket.pending;
  const borrowed=await client.takePreparedSendSocket(options,null);client.rearmSendSocketWhenClosed(borrowed.ws,null);
  if(change==='account')client.session.hashedEmail='other';
  if(change==='session')client.session.sessionId='other';
  if(change==='key')client.session.masterKeyExportedB64=Buffer.alloc(32,1).toString('base64');
  if(change==='team')client.session.activeTeamId='other';
  if(change==='cookie')client.session.cookies={auth_refresh_token:'other'};
  if(change==='http-cookie')client.http.getCookieMap=()=>({auth_refresh_token:'other'});
  if(change==='token')client.session.wsToken='other';
  if(change==='end')client.endInteractiveViewerSession();
  if(change==='new-send'){client.cancelSendSocketRearm();client.foregroundSendCount++;}
  borrowed.ws.close();await Promise.resolve();assert.equal(opened.length,1);client.endInteractiveViewerSession();
 });
}

for(const lifecycle of ['begin','end'] as const){
 // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
 it(`removes the pending close hook before ${lifecycle} can close metadata subscriptions`,async()=>{
  const {client,opened}=fixture();client.warmSendSocket();await client.preparedSendSocket.pending;
  const borrowed=await client.takePreparedSendSocket(options,null);
  const baselineListeners=borrowed.ws.listenerCount();
  client.rearmSendSocketWhenClosed(borrowed.ws,null);
  assert.equal(borrowed.ws.listenerCount(),baselineListeners+1);
  client.ownedMetadataSubscriptions.add(()=>{
   assert.equal(client.pendingSendSocketRearm,null,'pending rearm must be removed before metadata stop');
   assert.equal(borrowed.ws.listenerCount(),baselineListeners,'owned close hook must already be detached');
   borrowed.ws.close();
  });
  if(lifecycle==='begin'){
   client.beginInteractiveViewerSession();
   assert.equal(client.pendingSendSocketRearm,null);assert.equal(borrowed.ws.listenerCount(),baselineListeners);
   client.interactiveViewerAllowed=true;borrowed.ws.close();
  }else client.endInteractiveViewerSession();
  await Promise.resolve();assert.equal(opened.length,1,'ending or replacing the TUI lifecycle must not open auth');
  client.endInteractiveViewerSession();
 });
}
