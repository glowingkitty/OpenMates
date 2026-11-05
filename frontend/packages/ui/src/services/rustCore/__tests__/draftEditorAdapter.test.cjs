// contract-test-file: tooling
// Exact editor route source; inert editor/store/session ports only. No Svelte
// mount, real parser/Worker/IDB/crypto or browser/runtime proof.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const source=ts.transpileModule(fs.readFileSync(path.resolve(__dirname,'../draftEditorAdapter.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};},tick=()=>new Promise(r=>setImmediate(r));
function fixture(){const root=new AbortController(),save=deferred(),restore=deferred(),drain=deferred(),writes=[];let live=true,saves=0;
 const store={value:{currentChatId:'A',currentUserDraftVersion:0,hasUnsavedChanges:false,lastSavedContentMarkdown:null,isSaveInProgress:false,isSwitchingContext:false},update(fn){this.value=fn(this.value);}};
 const editor={isDestroyed:false,state:{doc:{text:'Original user content'}},getJSON(){return this.state.doc;},chain(){return{setContent:(content,options)=>({run:()=>{assert.equal(options.emitUpdate,false);writes.push(content);editor.state.doc=content;}})};}};
 const session={async save(input,signal,publish){saves++;await save.promise;publish({version:5});},async restore(id,signal,publish){await restore.promise;publish({version:5,markdown:'Restored user content'});},close:()=>drain.promise};
 const exports={};vm.runInNewContext(source,{exports,require(name){return {'svelte/store':{get:s=>s.value},'../drafts/draftState':{draftEditorUIState:store},'../../message_parsing/serializers':{tipTapToCanonicalMarkdown:doc=>doc.text},'../../components/enter_message/utils/markdownParser':{parseMarkdownToTiptap:text=>({text})}}[name];}});
 const route=exports.installDraftEditorRoute(editor,{session,signal:root.signal,current(){if(!live)throw Error('original_revoked');}});
 return{root,editor,store,save,restore,drain,writes,session,exports,route,revoke(){live=false;},saves:()=>saves};
}
test('no installed route is null; installed route sends through original session without replacing editor text',async()=>{
 const f=fixture();assert.equal(f.exports.routeDraftEditorSave('A',{}),null);const doc=f.editor.state.doc;
 const pending=f.exports.routeDraftEditorSave('A',f.editor);assert.equal(typeof pending.then,'function');f.save.resolve();await pending;assert.equal(f.editor.state.doc,doc);assert.equal(f.store.value.currentUserDraftVersion,5);assert.equal(f.store.value.lastSavedContentMarkdown,'Original user content');f.drain.resolve();await f.route.close();
});
test('typing while save awaits preserves new document and unsaved state',async()=>{
 const f=fixture(),pending=f.exports.routeDraftEditorSave('A',f.editor);f.editor.state.doc={text:'Newer input'};f.store.update(s=>({...s,hasUnsavedChanges:true}));f.save.resolve();await pending;
 assert.equal(f.editor.state.doc.text,'Newer input');assert.equal(f.store.value.hasUnsavedChanges,true);assert.equal(f.store.value.lastSavedContentMarkdown,null);f.drain.resolve();await f.route.close();
});
test('restore cannot overwrite typing performed during async read or already unsaved input',async()=>{
 const f=fixture(),pending=f.exports.routeDraftEditorRestore('A',f.editor);f.editor.state.doc={text:'Typed during read'};f.store.update(s=>({...s,hasUnsavedChanges:true}));f.restore.resolve();await pending;assert.equal(f.writes.length,0);assert.equal(f.editor.state.doc.text,'Typed during read');
 await f.exports.routeDraftEditorRestore('A',f.editor);assert.equal(f.writes.length,0);f.drain.resolve();await f.route.close();
});
test('original root revocation prevents late ack and stale cleanup from mutating current UI',async()=>{
 const f=fixture(),pending=f.exports.routeDraftEditorSave('A',f.editor),rejected=assert.rejects(pending,/original_revoked/);f.revoke();f.store.update(s=>({...s,currentChatId:'B',hasUnsavedChanges:true,isSaveInProgress:true}));f.save.resolve();await rejected;
 assert.equal(f.store.value.currentChatId,'B');assert.equal(f.store.value.isSaveInProgress,true);assert.equal(f.store.value.lastSavedContentMarkdown,null);f.drain.resolve();await f.route.close();
});
test('closed installed route remains restrictive tombstone and close awaits actual owner drain',async()=>{
 const f=fixture();let closed=false;const closing=f.route.close().then(()=>closed=true);await tick();assert.equal(closed,false);assert.equal(f.exports.hasDraftEditorRoute(f.editor),true);await assert.rejects(f.exports.routeDraftEditorSave('A',f.editor),/invalidated_snapshot/);assert.equal(f.saves(),0);f.drain.resolve();await closing;
});

test('unchanged current document restores through existing renderer port only at final original boundary',async()=>{
 const f=fixture(),pending=f.exports.routeDraftEditorRestore('A',f.editor);f.restore.resolve();await pending;assert.equal(f.writes.length,1);assert.equal(f.editor.state.doc.text,'Restored user content');assert.equal(f.store.value.currentUserDraftVersion,5);f.drain.resolve();await f.route.close();
});
