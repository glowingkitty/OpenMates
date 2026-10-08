/** The panel does not route away from the view behind it or consume its draft. */
import {createHash} from 'node:crypto';
import {deriveAppUrl} from './client.js';
import type {WorkspaceContext} from './tuiWorkspaceController.js';
import type {TuiState} from './tuiRenderer.js';
import {captureTuiWorkspaceOwner} from './tuiCachedWorkspaces.js';
import {createTuiSettingsState,openTuiSettingsPage,handleTuiSettingsKey,handleTuiSettingsCommand,type TuiSettingsContext} from './tuiSettings.js';

function ownerIdentity(context:WorkspaceContext):string {
  try {const session=context.client.getSession();return createHash('sha256').update(JSON.stringify([
    context.client.apiUrl,session.hashedEmail,session.createdAt,session.activeTeamId??null,session.masterKeyExportedB64,
  ])).digest('hex');} catch {return 'signed-out';}
}
export function closeTuiSettings(state:TuiState):void {
  if(state.settings)++state.settings.generation;
  const restore=state.settingsRestore;
  state.settings=null;state.settingsRestore=null;state.settingsOwnerCurrent=null;
  if(restore){state.focus=restore.focus;state.sidebarOpen=restore.sidebarOpen;}
}
export function fenceTuiSettingsView(state:TuiState):void {
  const panel=state.settings;
  if(!panel||panel.ownerStale||!state.settingsOwnerCurrent||state.settingsOwnerCurrent())return;
  ++panel.generation;panel.data={};panel.drafts={};panel.lastResult={};panel.dirty={};
  panel.profile={username:'',email:'',account:'',team:''};panel.oneTimeSecret=null;panel.secretRevealed=false;
  panel.busy=false;panel.editing=null;panel.confirmation=null;panel.ownerStale=true;
  panel.error='Account or team changed. Close and reopen Settings.';
}
function settingsContext(context:WorkspaceContext):TuiSettingsContext|null {
  const {state,client,render}=context;if(!state.settings)return null;
  return {client,state:state.settings,owner:()=>ownerIdentity(context),isOwnerCurrent:state.settingsOwnerCurrent??undefined,
    render,viewportHeight:context.terminal.height-8,close:()=>{closeTuiSettings(state);render();},webUrl:deriveAppUrl(client.apiUrl),
    // A remote CLI cannot launch a browser on the user's device. Its explicit
    // destination stays selectable in the panel instead of spawning a server GUI.
    openWeb:()=>{if(state.settings){state.settings.message='Open the web destination shown below in your browser.';render();}}};
}
export async function openTuiSettings(context:WorkspaceContext,route=''):Promise<void> {
  const {state,client,render}=context;
  if(state.form||state.questionEditor||state.paletteOpen)return;
  if(!state.settings){
    state.settingsRestore={focus:state.focus,sidebarOpen:state.sidebarOpen};
    state.sidebarOpen=false;state.focus='settings';state.chrome=null;
    state.settings=createTuiSettingsState(ownerIdentity(context),{authenticated:state.signedIn,webUrl:deriveAppUrl(client.apiUrl)});
    state.settings.profile.username=state.username??'';
    state.settingsOwnerCurrent=state.signedIn?captureTuiWorkspaceOwner(client):()=>!client.hasSession();
  }else state.focus='settings';
  const ctx=settingsContext(context)!;
  render();await openTuiSettingsPage(state.settings,route||'main',ctx);
}
export async function handleSettingsCommand(context:WorkspaceContext,arg:string):Promise<void> {
  const ctx=settingsContext(context);if(ctx)await handleTuiSettingsCommand(ctx,arg);
}
export async function handleSettingsKey(context:WorkspaceContext,chunk:string,key:Parameters<typeof handleTuiSettingsKey>[2]):Promise<boolean> {
  const ctx=settingsContext(context);if(!ctx)return false;
  return handleTuiSettingsKey(ctx,chunk,key);
}
