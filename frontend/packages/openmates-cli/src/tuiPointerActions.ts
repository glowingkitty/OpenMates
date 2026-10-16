/** Pointer activation reuses keyboard/command handlers and their validation. */
import type {WorkspaceContext} from './tuiWorkspaceController.js';
import type {TerminalKey} from './tuiTerminal.js';
import type {TuiPointerAction} from './tuiPointer.js';
import {closeTuiSettings} from './tuiSettingsShell.js';
import {handleQuestionPointer} from './tuiInteractiveQuestions.js';
import {sidebarPointerIds} from './tuiLayout.js';
import {paletteActions} from './tuiActions.js';
import {filterTasks} from './tuiTasksWorkspace.js';
import {TASK_STATUSES} from './tasksCli.js';
import {orderedWorkflowNodes} from './tuiWorkflowWorkspace.js';
import {filteredProjectFiles} from './tuiProjectsWorkspace.js';

export async function handleTuiPointer(context:WorkspaceContext,action:TuiPointerAction,
  keyboard:(chunk:string,key:TerminalKey)=>Promise<void>):Promise<void> {
  const {state,render}=context;
  if(state.textSelection||state.startup||state.privacyOffer)return;
  if(state.modelSelector?.open && !(action.kind==='command' && (action.command==='/model' || action.command.startsWith('/model-action ')))){
    await context.command('/model-action close');
    return;
  }
  if(state.settings&&!(action.kind==='command'&&action.command.startsWith('/settings'))){
    // Only visible main-pane targets exist in a split view; narrow settings has
    // no underlying targets. Returning focus restores the view before its action.
    closeTuiSettings(state);
  }
  if(action.kind==='question'){await handleQuestionPointer(context,action);return;}
  if(action.kind==='command'){await context.command(action.command);return;}
  if(action.kind==='focus'){state.focus=action.focus;render();return;}
  if(action.kind==='key'){
    if(action.focus)state.focus=action.focus;
    else if(state.form||state.paletteOpen)state.focus='content';
    await keyboard(action.chunk??'',{name:action.name,ctrl:action.ctrl});return;
  }
  if(!Number.isInteger(action.index)||action.index<0)return;
  let index=action.index;
  switch(action.target){
    case 'sidebar':{
      const ids=sidebarPointerIds(state);
      index=action.id?ids.indexOf(action.id):index;
      if(index<0||!ids[index])return;
      state.sidebarIndex=index;state.focus='sidebar';break;
    }
    case 'palette':{
      if(!state.paletteOpen)return;
      const actions=paletteActions(state.paletteQuery);
      index=action.id?actions.findIndex(item=>item.command===action.id):index;
      if(index<0||!actions[index])return;
      state.paletteIndex=index;state.focus='content';break;
    }
    case 'form-field':{
      const form=state.form;if(!form||form.busy)return;
      index=action.id?form.fields.findIndex(field=>field.name===action.id):index;
      if(index<0||!form.fields[index])return;
      form.fieldIndex=index;state.focus='content';break;
    }
    case 'task':{
      if(state.screen!=='tasks'&&!(state.screen==='project'&&state.projectTab==='tasks'))return;
      const status=action.column===undefined?undefined:TASK_STATUSES[action.column];
      if(action.column!==undefined&&!status)return;
      const tasks=filterTasks(state.tasks,state.filter,status);
      if(!action.id&&!action.activate&&state.screen==='tasks'){
        state.taskStatusFilter=status??'';state.selectedIndex=Math.min(index,Math.max(0,tasks.length-1));state.focus='content';render();return;
      }
      index=action.id?tasks.findIndex(task=>task.taskId===action.id):index;
      if(index<0||!tasks[index])return;
      state.taskStatusFilter=status??'';state.selectedIndex=index;state.focus='content';
      // Project task Enter uses the combined list rather than the board column.
      if(state.screen==='project')state.selectedIndex=filterTasks(state.tasks,state.filter).findIndex(task=>task.taskId===tasks[index].taskId);
      break;
    }
    case 'workflow-node':{
      if(state.screen!=='workflow')return;
      const graph=state.workflowTab==='runs'?state.workflowRunGraph:state.activeWorkflow?.graph;
      const nodes=graph?orderedWorkflowNodes(graph):[];
      index=action.id?nodes.findIndex(node=>node.id===action.id):index;
      if(index<0||!nodes[index])return;
      state.selectedWorkflowNodeIndex=index;state.focus='content';break;
    }
    case 'workflow-run':{
      if(state.screen!=='workflow'||state.workflowTab!=='runs')return;
      index=action.id?state.workflowRuns.findIndex(run=>run.id===action.id):index;
      if(index<0||!state.workflowRuns[index])return;
      state.selectedWorkflowRunIndex=index;state.focus='content';
      if(action.activate){await keyboard('r',{name:''});return;}
      break;
    }
    case 'content':
      if(action.id){
        if(state.screen!=='project'||state.projectTab!=='files')return;
        index=filteredProjectFiles(state.projectFiles,state.filter).findIndex(file=>file.id===action.id);
        if(index<0)return;
      }
      state.selectedIndex=index;state.focus='content';break;
  }
  state.followSelection=true;
  if(action.activate)await keyboard(action.chunk??'',{name:action.name??'return'});
  else render();
}
