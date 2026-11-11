// Preview states for the one-workflow editor pane:
// /dev/preview/workflows/WorkflowEditorPane?chrome=0[&variant=draft|saved|saved-enabled]
// The default is a saved, paused workflow. Version 1 keeps version history offline.
import type { WorkflowDetail, WorkflowGraph } from '../../stores/workflowWorkspaceStore';
import type { WorkflowEditorDraft, WorkflowEditorPaneState } from './workflowEditorPane';

const graph: WorkflowGraph = {
  version: 2,
  trigger_node_id: 'schedule',
  nodes: [
    { id: 'schedule', type: 'schedule_trigger', title: 'Monday at 09:00', config: { schedule: { type: 'weekly', weekdays: ['monday'], time: '09:00', timezone: 'Europe/Berlin' } } },
    { id: 'weather', type: 'app_skill_action', title: 'Get weather', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin' } } },
    { id: 'message', type: 'send_chat_message', title: 'Send summary', config: { title: 'Weather', message: 'Weather summary' } }
  ],
  edges: [{ from: 'schedule', to: 'weather' }, { from: 'weather', to: 'message' }]
};

const workflow: WorkflowDetail = {
  id: 'workflow-preview',
  title: 'Weekly school weather brief',
  description: 'Summarize Monday weather before school.',
  category: 'general_knowledge',
  icon: 'cloud-sun',
  status: 'active',
  enabled: false,
  current_version_id: 'version-1',
  version: 1,
  created_at: Date.now() / 1000 - 3600,
  graph
};

const draft: WorkflowEditorDraft = {
  title: workflow.title,
  description: workflow.description ?? '',
  category: 'general_knowledge',
  icon: 'cloud-sun',
  graph
};

const emit = (name: string, detail?: unknown) => window.dispatchEvent(new CustomEvent(name, { detail }));

const common = {
  onClose: () => emit('workflow-preview-close'),
  onError: (_message: string | null) => {},
  onStateChange: (_state: WorkflowEditorPaneState) => {}
};

const savedSource = (enabled: boolean) => ({
  kind: 'saved' as const,
  workflow: { ...workflow, enabled },
  activeTab: 'template' as const,
  selectedRunId: null,
  runsHref: '#runs',
  editorHref: '#details',
  onTabChange: (_tab: 'template' | 'runs') => {},
  onOpenRun: (_runId: string | null) => {},
  onOpenEditor: () => {},
  onShare: () => {},
  onDeleted: () => {},
  onRequestNavigation: (action: () => void | Promise<void>) => { void action(); },
  authoring: null
});

const props = { ...common, source: savedSource(false) };

export default props;
export const variants = {
  draft: {
    ...common,
    source: {
      kind: 'draft' as const,
      draft,
      saving: false,
      preview: null,
      partialNotice: null,
      info: null,
      aiAddedNodeIds: [],
      aiEditedNodeIds: [],
      onChange: (next: WorkflowEditorDraft) => emit('workflow-preview-draft-change', { title: next.title }),
      onSave: (next: WorkflowEditorDraft) => emit('workflow-preview-save-draft', { title: next.title }),
      onDraftStateChange: (_hasDraft: boolean) => {}
    }
  },
  saved: props,
  'saved-enabled': { ...common, source: savedSource(true) }
};
