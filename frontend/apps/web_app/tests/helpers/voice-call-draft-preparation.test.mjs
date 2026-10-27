// Account-free execution of the real component export, with observable stores.
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require=createRequire(new URL('../../../../packages/ui/package.json',import.meta.url));
const ts=require('typescript');
const component=fs.readFileSync(new URL('../../../../packages/ui/src/components/enter_message/MessageInput.svelte',import.meta.url),'utf8');
const start=component.indexOf('export async function prepareVoiceCallDraft(');
const method=component.slice(start,component.indexOf('function handleSaveDraftBeforeSwitch',start)).replace('export ','');
const compiled=ts.transpileModule(method,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function store(value){
  const listeners=new Set();
  return {value,listeners,subscribe(fn){listeners.add(fn);fn(this.value);return()=>listeners.delete(fn);},
    set(value){this.value=value;for(const fn of [...listeners])fn(value);}};
}
function fixture({ready=false,save=true}={}){
  const timers=new Map();let nextTimer=0;
  const draft=store({currentChatId:ready?'target':'prior-welcome',isSwitchingContext:!ready});
  const auth=store({isAuthenticated:true}),profile=store({user_id:'owner'}),team=store({teamId:null,epoch:1});
  const editor={isDestroyed:false};const calls=[];
  const context=vm.createContext({editor,globalEditor:editor,composerDestroyed:false,queuedEdit:null,currentChatId:'target',
    authStore:auth,userProfile:profile,activeTeamContext:team,draftEditorUIState:draft,pendingVoiceCallDraftWaits:new Set(),
    get:store=>store.value,getEditorInstance:()=>context.globalEditor,
    getActiveTeamContextSnapshot:()=>({...team.value}),
    isActiveTeamContext:(id,epoch)=>team.value.teamId===id&&team.value.epoch===epoch,
    setTimeout:(fn,delay)=>{assert.equal(delay,2000);const id=++nextTimer;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
    syncTextOnlyDomToEditorBeforeDraftSave:()=>calls.push('sync'),
    flushSaveDraftAndWaitForIdle:async(...args)=>{calls.push(args);return save&&draft.value.currentChatId===args[1]&&!draft.value.isSwitchingContext&&context.globalEditor===args[0];},
  });
  vm.runInContext(compiled,context);
  return {context,draft,auth,profile,team,timers,calls,run:()=>context.prepareVoiceCallDraft('target'),
    expire:()=>{for(const fn of [...timers.values()])fn();},
    clean:()=>{assert.equal(timers.size,0);for(const store of [draft,auth,profile,team])assert.equal(store.listeners.size,0);assert.equal(context.pendingVoiceCallDraftWaits.size,0);}};
}

// contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.audio.single-owner,video-call.privacy
test('waits for genuine same-editor store adoption and settled context, then requires the strict local save',async()=>{
  const f=fixture(),pending=f.run();assert.equal(f.calls.length,0);
  f.draft.set({currentChatId:'target',isSwitchingContext:true});await Promise.resolve();assert.equal(f.calls.length,0);
  f.draft.set({currentChatId:'target',isSwitchingContext:false});assert.equal(await pending,true);
  assert.equal(f.calls[0],'sync');assert.equal(f.calls[1][0],f.context.editor);assert.equal(f.calls[1][1],'target');
  assert.equal(f.calls[1][2].suppressQueuedEditResaves,false);f.clean();
});
// contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.audio.single-owner,video-call.privacy
test('already-ready context saves without retaining any subscription or timeout',async()=>{
  const f=fixture({ready:true});const pending=f.run();assert.equal(f.timers.size,0);assert.equal(await pending,true);f.clean();
});
// contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.audio.single-owner,video-call.privacy
test('timeout refuses stale context without saving or changing its ID',async()=>{
  const f=fixture(),pending=f.run();f.expire();assert.equal(await pending,false);assert.equal(f.calls.length,0);
  assert.equal(f.draft.value.currentChatId,'prior-welcome');f.clean();
});
for(const kind of ['third-id','reverted-id','auth','user','team','prop','editor','global-editor','destroyed-editor','queued-edit','destroy']){
  // contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.audio.single-owner,video-call.privacy
  test(`rejects ${kind} during the existing handoff`,async()=>{
    const f=fixture(),pending=f.run();
    if(kind==='third-id')f.draft.set({currentChatId:'unrelated',isSwitchingContext:false});
    if(kind==='reverted-id'){f.draft.set({currentChatId:'target',isSwitchingContext:true});f.draft.set({currentChatId:'prior-welcome',isSwitchingContext:false});}
    if(kind==='auth')f.auth.set({isAuthenticated:false});
    if(kind==='user')f.profile.set({user_id:'other'});
    if(kind==='team')f.team.set({teamId:null,epoch:2});
    if(kind==='prop')f.context.currentChatId='unrelated';
    if(kind==='editor')f.context.editor={isDestroyed:false};
    if(kind==='global-editor')f.context.globalEditor={isDestroyed:false};
    if(kind==='destroyed-editor')f.context.editor.isDestroyed=true;
    if(kind==='queued-edit')f.context.queuedEdit={};
    if(kind==='destroy'){f.context.composerDestroyed=true;for(const cancel of f.context.pendingVoiceCallDraftWaits)cancel();}
    if(['prop','editor','global-editor','destroyed-editor','queued-edit'].includes(kind))f.draft.set({...f.draft.value});
    assert.equal(await pending,false);assert.equal(f.calls.length,0);f.clean();
  });
}
// contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.audio.single-owner,video-call.privacy
test('strict local-save refusal is still a startup failure after readiness',async()=>{
  const f=fixture({ready:true,save:false});assert.equal(await f.run(),false);assert.equal(f.calls.length,2);f.clean();
});
for(const kind of ['user','editor','prop','same-id-switch']){
  // contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.audio.single-owner,video-call.privacy
  test(`rechecks ${kind} after the awaited strict local save`,async()=>{
    const f=fixture({ready:true});let finish;
    f.context.flushSaveDraftAndWaitForIdle=()=>new Promise(resolve=>{finish=resolve;});
    const pending=f.run();await Promise.resolve();
    if(kind==='user')f.profile.set({user_id:'other'});
    if(kind==='editor')f.context.editor={isDestroyed:false};
    if(kind==='prop')f.context.currentChatId='other';
    if(kind==='same-id-switch')f.draft.set({currentChatId:'target',isSwitchingContext:true});
    finish(true);assert.equal(await pending,false);f.clean();
  });
}
