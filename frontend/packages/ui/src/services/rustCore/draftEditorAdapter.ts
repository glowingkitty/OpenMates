/** Thin TipTap/Svelte adapter. Markdown conversion and UI state reuse existing
 * renderer utilities. The ORIGINAL session resource owns every headless draft
 * operation. No plaintext storage or direct crypto/network access exists here.
 */
import type {Editor} from '@tiptap/core';
import {get} from 'svelte/store';
import {draftEditorUIState} from '../drafts/draftState';
import {tipTapToCanonicalMarkdown} from '../../message_parsing/serializers';
import {parseMarkdownToTiptap} from '../../components/enter_message/utils/markdownParser';
import type {DraftEditorSession} from './productionDraftBinding';
interface Route{save(chatId:string|undefined):Promise<void>;restore(chatId:string|null):Promise<void>;close():Promise<void>}
const routes=new WeakMap<Editor,Route>();
/** Install only after explicit legacy producer retirement on this exact editor.
 * Closed routes stay as restrictive tombstones: logout/failure must never cause
 * a stale editor to resume retired legacy persistence automatically.
 */
export function installDraftEditorRoute(editor:Editor,input:{session:DraftEditorSession;signal:AbortSignal;current():void}):{close():Promise<void>}{
 if(routes.has(editor)||input.signal.aborted||editor.isDestroyed)throw Error('draft_editor_route_unavailable');
 let uiRevision=0,closed=false,closing:Promise<void>|null=null;const pending=new Set<Promise<void>>();
 const current=()=>{if(closed||input.signal.aborted||editor.isDestroyed)throw Error('invalidated_snapshot');input.current();};
 const context=(chatId:string|null|undefined)=>{current();const state=get(draftEditorUIState);const id=chatId??state.currentChatId;if(!id||state.currentChatId!==id||state.isSwitchingContext)throw Error('unsupported_draft_context');return id;};
 const own=(task:Promise<void>)=>{pending.add(task);void task.catch(()=>undefined).finally(()=>pending.delete(task));return task;};
 const markFailure=(id:string,revision:number)=>{try{current();}catch{return;}if(revision!==uiRevision)return;draftEditorUIState.update(state=>state.currentChatId===id?{...state,hasUnsavedChanges:true,isSaveInProgress:false}:state);};
 const save=(chatId:string|undefined):Promise<void>=>{
  const revision=++uiRevision;let id:string,document:Editor['state']['doc'],markdown:string;
  try{id=context(chatId);document=editor.state.doc;markdown=tipTapToCanonicalMarkdown(editor.getJSON());}catch(error){return Promise.reject(error);}
  const task=(async()=>{try{
   current();draftEditorUIState.update(state=>state.currentChatId===id?{...state,isSaveInProgress:true}:state);
   await input.session.save({chatId:id,markdown},input.signal,result=>{
    current();if(revision!==uiRevision||get(draftEditorUIState).currentChatId!==id||editor.state.doc!==document)return;
    draftEditorUIState.update(state=>state.currentChatId===id?{...state,currentUserDraftVersion:result.version,lastSavedContentMarkdown:markdown,hasUnsavedChanges:false,isSaveInProgress:false}:state);
   });
   current();if(editor.state.doc!==document)markFailure(id,revision);
  }catch(error){markFailure(id,revision);throw error;}})();return own(task);
 };
 const restore=(chatId:string|null):Promise<void>=>{
  const revision=++uiRevision;let id:string,document:Editor['state']['doc'];try{id=context(chatId);const ui=get(draftEditorUIState);if(ui.hasUnsavedChanges||ui.isSaveInProgress)return Promise.resolve();document=editor.state.doc;}catch(error){return Promise.reject(error);}
  const task=(async()=>{await input.session.restore(id,input.signal,result=>{
   current();const ui=get(draftEditorUIState);if(revision!==uiRevision||ui.currentChatId!==id||ui.hasUnsavedChanges||ui.isSaveInProgress||editor.state.doc!==document)return;
   // Parse before the final synchronous editor write; typing during the awaited
   // Rust/IDB work preserves the original user document and discards this view.
   const content=parseMarkdownToTiptap(result.markdown,true);current();if(editor.state.doc!==document)return;
   editor.chain().setContent(content,{emitUpdate:false}).run();
   draftEditorUIState.update(state=>state.currentChatId===id?{...state,currentUserDraftVersion:result.version,lastSavedContentMarkdown:result.markdown,hasUnsavedChanges:false,isSaveInProgress:false}:state);
  });})();return own(task);
 };
 function close():Promise<void>{if(closing)return closing;closed=true;uiRevision++;input.signal.removeEventListener('abort',abort);
  closing=(async()=>{const outcomes=await Promise.allSettled([input.session.close(),...pending]);if(outcomes[0].status==='rejected')throw outcomes[0].reason;})();return closing;}
 const abort=()=>{void close().catch(()=>undefined);};
 const route=Object.freeze({save,restore,close});routes.set(editor,route);input.signal.addEventListener('abort',abort,{once:true});if(input.signal.aborted)abort();return Object.freeze({close});
}
export function hasDraftEditorRoute(editor:Editor|undefined):boolean{return !!editor&&routes.has(editor);}
export function routeDraftEditorSave(chatId:string|undefined,editor:Editor|undefined):Promise<void>|null{return editor?routes.get(editor)?.save(chatId)??null:null;}
export function routeDraftEditorRestore(chatId:string|null,editor:Editor):Promise<void>|null{return routes.get(editor)?.restore(chatId)??null;}
